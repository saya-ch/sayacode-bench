"""正式三 agent 对比：3 agent × 40 题 × 2 重复 = 240 次，并发 8。

- 顺序跑三个 agent（避免 24 容器超内存）
- 每个 trial 唯一 job 名；支持 --skip-existing 断点续跑（Docker 崩溃后继续）
- 每 agent 开始前清理 Docker 网络（每 trial 占 2 个，池约 17）
- 结果写 <out>/<agent>/rows.json
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path(r"C:\develop\sayacode-bench")
sys.path.insert(0, str(BENCH / "src"))
sys.path.insert(0, str(BENCH / "scripts"))
sys.path.insert(0, r"C:\sb\hard")

from harbor.models.trial.config import AgentConfig, EnvironmentConfig  # noqa: E402

from sayacode_bench.execution import run_official_trial  # noqa: E402
from test_agent import build as build_agent, env_cfg  # noqa: E402  (复用已验证的三 agent 构造)

TASKS = Path(r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks")
SAMPLE = BENCH / "studies" / "sample-40-final.json"
AGENTS = ("sayacode", "mini-swe", "codex")


def prune_networks() -> None:
    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False)


def container_mem_mb() -> float:
    """当前所有 trial 容器的总内存（MB）。"""
    import re as _re
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return 0.0
    total = 0.0
    for line in out.stdout.splitlines():
        m = _re.match(r"([\d.]+)(B|KiB|MiB|GiB)", line.strip())
        if not m:
            continue
        v, u = float(m.group(1)), m.group(2)
        total += {"B": v / 1e6, "KiB": v / 1e3, "MiB": v, "GiB": v * 1024}[u]
    return total


class AdaptiveSemaphore:
    """按容器总内存动态调整的并发信号量（内存高降并发，低升并发）。"""

    def __init__(self, max_limit: int) -> None:
        self.max_limit = max_limit
        self.limit = max_limit
        self.active = 0
        self._cv = asyncio.Condition()

    async def acquire(self) -> None:
        async with self._cv:
            while self.active >= self.limit:
                await self._cv.wait()
            self.active += 1

    async def release(self) -> None:
        async with self._cv:
            self.active -= 1
            self._cv.notify_all()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.release()

    async def set_limit(self, n: int) -> None:
        async with self._cv:
            self.limit = max(1, min(self.max_limit, n))
            self._cv.notify_all()


_VERIFIER_SEM: asyncio.Semaphore | None = None


def install_verifier_throttle(limit: int) -> None:
    """限制同时运行的验证器数量（验证阶段内存峰值高）。monkey-patch Harbor 的两个 verifier 入口。"""
    global _VERIFIER_SEM
    if _VERIFIER_SEM is not None:
        return
    _VERIFIER_SEM = asyncio.Semaphore(max(1, limit))
    from harbor.trial.trial import Trial

    orig_sep = Trial._run_separate_verifier
    orig_shared = Trial._run_shared_verifier

    async def throttled_sep(self, *a, **kw):
        async with _VERIFIER_SEM:
            return await orig_sep(self, *a, **kw)

    async def throttled_shared(self, *a, **kw):
        async with _VERIFIER_SEM:
            return await orig_shared(self, *a, **kw)

    Trial._run_separate_verifier = throttled_sep
    Trial._run_shared_verifier = throttled_shared
    print(f"已安装 verifier 限流：最多 {limit} 个并发验证", flush=True)


async def mem_supervisor(sem: AdaptiveSemaphore, tag: str) -> None:
    """每 5s 采样容器总内存：>5GB 降到 2 并发，>3.5GB 降到 4，否则升到 max。"""
    while True:
        try:
            mem = container_mem_mb()
            if mem > 5000:
                await sem.set_limit(2)
            elif mem > 3500:
                await sem.set_limit(4)
            else:
                await sem.set_limit(sem.max_limit)
            print(f"[{tag}] mem={mem:.0f}MB limit={sem.limit} active={sem.active}", flush=True)
        except Exception:
            pass
        await asyncio.sleep(5)


async def run_agent(name: str, tasks: list[str], out_root: Path, repeats: int, concurrency: int, skip_existing: bool) -> list[dict]:
    out = out_root / name
    out.mkdir(parents=True, exist_ok=True)
    prune_networks()
    agent = build_agent(name)
    env = env_cfg()
    sem = AdaptiveSemaphore(concurrency)
    monitor = asyncio.create_task(mem_supervisor(sem, name))
    rows: list[dict] = []

    # 归档无 reward 的残留 job（Docker 崩溃导致），否则 Harbor 以身份冲突拒绝重跑。
    import shutil
    import time as _time
    jobs_dir = out / "jobs"
    if jobs_dir.is_dir():
        abandoned = out / f"abandoned-{int(_time.time())}"
        moved = 0
        for job_dir in jobs_dir.iterdir():
            if job_dir.is_dir() and not list(job_dir.glob("instance_*/verifier/reward.txt")):
                abandoned.mkdir(parents=True, exist_ok=True)
                shutil.move(str(job_dir), str(abandoned / job_dir.name))
                moved += 1
        if moved:
            print(f"[{name}] 归档 {moved} 个无结果 job", flush=True)

    async def one(tid: str, repeat: int) -> None:
        async with sem:
            job = f"{name}-{tid.replace('instance_', '')[:34]}-r{repeat}"
            if skip_existing and list((out / "jobs" / job).glob("instance_*/verifier/reward.txt")):
                rows.append({"task_id": tid, "repeat": repeat, "reward": "skipped", "status": "skipped"})
                return
            print(f"[{name}] RUN {tid[:48]} r{repeat}", flush=True)
            try:
                rec = await run_official_trial(
                    TASKS / tid, out / "jobs", job, agent, env,
                    configuration=name, repeat=repeat, canonical_model="DeepSeek-V4.1-Flash" if name == "sayacode" else "auto-hy3",
                    endpoint="magpie",
                )
                reward, status = rec.get("original_reward"), rec.get("status")
            except Exception as exc:  # noqa: BLE001
                reward, status = None, f"exception:{type(exc).__name__}"
            rows.append({"task_id": tid, "repeat": repeat, "reward": reward, "status": status})
            print(f"[{name}]   -> {status} reward={reward}", flush=True)

    await asyncio.gather(*[one(t, r) for t in tasks for r in range(1, repeats + 1)])
    monitor.cancel()
    (out / "rows.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("reward") == 1.0)
    valid = sum(1 for r in rows if isinstance(r.get("reward"), (int, float)))
    print(f"[{name}] 完成：有效 {valid}/{len(rows)}，PASS {ok}", flush=True)
    return rows


async def main_async(args) -> int:
    spec = json.loads(SAMPLE.read_text(encoding="utf-8"))
    tasks = [t["task_id"] for t in spec["tasks"]]
    print(f"题集: {len(tasks)} 题；agent: {AGENTS}；repeats={args.repeats} concurrency={args.concurrency}", flush=True)
    install_verifier_throttle(args.verifier_limit)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    for name in AGENTS:
        rows = await run_agent(name, tasks, out_root, args.repeats, args.concurrency, args.skip_existing)
        (out_root / f"{name}-summary.json").write_text(
            json.dumps({"agent": name, "n": len(rows)}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("全部完成", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--concurrency", type=int, default=12)
    p.add_argument("--verifier-limit", type=int, default=1)
    p.add_argument("--skip-existing", action="store_true")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
