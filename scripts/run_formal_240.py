"""正式三 agent 对比：3 agent × 40 题 × 2 重复 = 240 次，并发 8。

- 顺序跑三个 agent（避免 24 容器超内存）
- 每个 trial 唯一 job 名；支持 --skip-existing 断点续跑（Docker 崩溃后继续）。
  判据是「有 reward 或显式 terminal 标记」，不再认 model.patch，避免空 patch 永久 pending。
- 三个 agent 的规范模型身份统一为 ``auto-hy3``（SAYACODE 的 ``DeepSeek-V4.1-Flash`` 只是产品 profile 别名）
- 每 agent 开始前清理 Docker 网络（每 trial 占 2 个，池约 17）
- 结果写 <out>/<agent>/rows.json
- 仓外路径集中在 ``scripts/locked_agents.py:FormalPaths``，可用 ``SAYACODE_BENCH_*`` 或参数覆盖
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


def _bench_root() -> Path:
    """仓库根：优先环境变量，否则从本文件推导（不再硬编码绝对路径）。

    历史上这里写死 ``Path(r"C:\\develop\\sayacode-bench")``，导致：
    ① 换机器 / 换克隆目录就跑不起来；
    ② 模块级 ``sys.path.insert`` 在任何 import 时都执行，污染测试进程的
       ``sys.path``，使「变异后在沙箱副本里跑」被原仓库代码掩盖
       （2026-11-07 P1 变异检验时实测到）。
    """
    override = os.environ.get("SAYACODE_BENCH_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1]


BENCH = _bench_root()


def _ensure_on_path(directory: Path) -> None:
    """把目录加到 ``sys.path`` **末尾**（若尚未存在）。

    用 append 而非 insert(0)：避免遮蔽调用方已装好的同名包。
    """
    entry = str(directory)
    if entry not in sys.path:
        sys.path.append(entry)


_ensure_on_path(BENCH / "src")
_ensure_on_path(BENCH / "scripts")

from harbor.models.trial.config import AgentConfig  # noqa: E402,F401  (re-export 给旧调用方)
from locked_agents import AGENTS, CANONICAL_MODEL, FormalPaths, build_agent, env_cfg  # noqa: E402

from sayacode_bench import trialdir  # noqa: E402
from sayacode_bench.execution import run_official_trial  # noqa: E402

VERIFIER_CFG = None


def prune_networks() -> None:
    subprocess.run(
        ["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False
    )


def archive_incomplete_jobs(out: Path, name: str) -> int:
    """归档「无 reward、无终态标记、也无 patch」的残留 job（Docker 崩溃导致）。

    否则 Harbor 会以身份冲突拒绝重跑。

    **判据必须按内容识别，不能按 ``instance_`` 前缀**（历史 bug）：
    旧实现用 ``job_dir.glob("instance_*/verifier/reward.txt")``，接入 SWE-EVO
    （trial 目录形如 ``sweevo-...__random``）后一个都匹配不上，于是**已完成的
    job 被当成「无结果」移进 abandoned/，等于丢数据**。实测 pilot1 的 10/10 个
    已完成 job 都会被误归档。见 ``docs/review/2026-11-07/R3-infrastructure.md`` S1。
    """
    import shutil
    import time as _time

    jobs_dir = out / "jobs"
    if not jobs_dir.is_dir():
        return 0
    abandoned = out / f"abandoned-{int(_time.time())}"
    moved = 0
    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue
        done = (
            trialdir.has_trial_file(job_dir, *trialdir.REWARD_PARTS)
            or trialdir.has_trial_file(job_dir, *trialdir.TERMINAL_PARTS)
            or trialdir.has_trial_file(job_dir, *trialdir.PATCH_PARTS)
        )
        if not done:
            abandoned.mkdir(parents=True, exist_ok=True)
            shutil.move(str(job_dir), str(abandoned / job_dir.name))
            moved += 1
    if moved:
        print(f"[{name}] 归档 {moved} 个无结果 job", flush=True)
    return moved


# 目标内存利用率：Docker VM 8GB，目标 6GB（75%）。留 2GB 给突发（验证器峰值 2.26GB）。
TARGET_MEM_MB = 6000.0
HARD_CEIL_MB = 7000.0  # 超过立即收紧


def parse_docker_stats_mb(text: str) -> float:
    """把 ``docker stats --format '{{.MemUsage}}'`` 的输出解析成总 MB。

    纯函数，便于在不起 Docker 的情况下验证单位换算（这是历史事故点之一：
    单位解析错会让"内存自适应"失效，进而打爆 WSL）。
    """
    import re as _re

    total = 0.0
    for line in (text or "").splitlines():
        m = _re.match(r"([\d.]+)(B|KiB|MiB|GiB)", line.strip())
        if not m:
            continue
        v, u = float(m.group(1)), m.group(2)
        total += {"B": v / 1e6, "KiB": v / 1e3, "MiB": v, "GiB": v * 1024}[u]
    return total


def update_ema(previous: float, raw: float) -> float:
    """EMA（α=0.3）平滑采样抖动；首次采样直接取原值，避免从 0 爬升。"""
    return raw if previous == 0 else 0.7 * previous + 0.3 * raw


def decide_limit(ema: float, max_limit: int) -> int:
    """按平滑后的内存占用决定并发上限（多级阈值，必须返回 [1, max_limit]）。"""
    if ema > HARD_CEIL_MB:
        return 1
    if ema > TARGET_MEM_MB:
        return 2
    if ema > 5000:
        return 4
    if ema > 4000:
        return 6
    if ema > 3000:
        return 9
    return max(1, max_limit)


def decide_verifier_limit(ema: float) -> int:
    """验证器并发：内存紧（>4.5GB）时收紧到 1，否则放大到 2。"""
    return 1 if ema > 4500 else 2


def _record_complete(job_dir: Path) -> bool:
    """``normalized.json`` 是否已收尾（阶段1 跳过验证器时的唯一完成信号）。"""
    record_path = job_dir / "normalized.json"
    if not record_path.is_file():
        return False
    try:
        return json.loads(record_path.read_text(encoding="utf-8")).get("record_complete") is True
    except (OSError, ValueError):
        return False


def should_skip_existing(job_dir: Path, *, skip_existing: bool) -> bool:
    """续跑判据：有 reward / 有显式 terminal / normalized 已收尾。

    判据必须按内容识别（``trialdir``），不能按 ``instance_`` 前缀 —— 接入
    SWE-EVO 后旧判据会让每个已完成 job 都匹配不上（见 ``archive_incomplete_jobs``）。
    """
    if not skip_existing:
        return False
    return (
        trialdir.has_trial_file(job_dir, *trialdir.REWARD_PARTS)
        or trialdir.has_trial_file(job_dir, *trialdir.TERMINAL_PARTS)
        or _record_complete(job_dir)
    )


def container_mem_mb() -> float:
    """当前所有 trial 容器的总内存（MB）。取不到时返回 0.0（调用方需容忍）。"""
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return 0.0
    return parse_docker_stats_mb(out.stdout)


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


_VERIFIER_SEM: AdaptiveSemaphore | None = None


def install_verifier_throttle(limit: int) -> None:
    """限制同时运行的验证器数量（验证阶段内存峰值高）。monkey-patch Harbor 的两个 verifier 入口。"""
    global _VERIFIER_SEM
    if _VERIFIER_SEM is not None:
        return
    _VERIFIER_SEM = AdaptiveSemaphore(max(1, limit))
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
    """EMA 平滑 + 滞回的多级限流，并把目标内存维持在 TARGET_MEM_MB 附近。

    - EMA（α=0.3）平滑采样抖动，避免抖动式开关
    - 多级阈值 + 滞回（降到某档后要回落到更低档才回升）
    - 同时动态调整验证器并发（内存紧时 1，宽松时 2）
    决策逻辑抽成 ``update_ema`` / ``decide_limit`` / ``decide_verifier_limit``
    纯函数，便于在不起 Docker 的情况下验证（历史上打爆过 WSL）。
    """
    ema = 0.0
    verifier_limit = 1
    while True:
        try:
            raw = container_mem_mb()
            ema = update_ema(ema, raw)
            await sem.set_limit(decide_limit(ema, sem.max_limit))
            # 动态验证器并发：内存 >4.5GB 收紧到 1，否则放宽到 2
            if _VERIFIER_SEM is not None:
                want = decide_verifier_limit(ema)
                if want != verifier_limit:
                    await _VERIFIER_SEM.set_limit(want)
                    verifier_limit = want
            print(
                f"[{tag}] mem={raw:.0f}MB ema={ema:.0f}MB limit={sem.limit} "
                f"verifier={verifier_limit} active={sem.active}",
                flush=True,
            )
        except Exception:
            pass
        await asyncio.sleep(3)


async def run_agent(
    name: str,
    tasks: list[str],
    out_root: Path,
    repeats: int,
    concurrency: int,
    skip_existing: bool,
    paths: FormalPaths,
) -> list[dict]:
    out = out_root / name
    out.mkdir(parents=True, exist_ok=True)
    prune_networks()
    agent = build_agent(name, paths, profile_dir=out)
    env = env_cfg(paths)
    sem = AdaptiveSemaphore(concurrency)
    monitor = asyncio.create_task(mem_supervisor(sem, name))
    rows: list[dict] = []

    archive_incomplete_jobs(out, name)

    async def one(tid: str, repeat: int) -> None:
        async with sem:
            # 题集里的 task_id 可能带题库前缀（``tb21/code-from-image``、
            # ``pro-v2/instance_xxx``），而题目录名是不带前缀的 native_id。
            # 直接用 tid 会同时错两处：
            #   1) job 名里出现 ``/``，被当成子目录
            #   2) tasks_root / tid 多套一层，找不到题目录 → ValueError
            # SWE-bench 的 ``instance_xxx`` 不含 ``/``，不受影响。
            stem = tid.split("/", 1)[1] if "/" in tid else tid
            job = f"{name}-{stem.replace('instance_', '')[:34]}-r{repeat}"
            job_dir = out / "jobs" / job
            # 阶段1 用 --skip-verifier，完成时既无 reward.txt 也无 terminal.json，
            # 只有 normalized.json（record_complete=True）。续跑必须认它，否则会重复进入
            # run_official_trial 并撞 request hash 不一致的 ValueError。
            if should_skip_existing(job_dir, skip_existing=skip_existing):
                rows.append(
                    {"task_id": tid, "repeat": repeat, "reward": "skipped", "status": "skipped"}
                )
                return
            print(f"[{name}] RUN {tid[:48]} r{repeat}", flush=True)
            try:
                rec = await run_official_trial(
                    paths.tasks_root / stem,
                    out / "jobs",
                    job,
                    agent,
                    env,
                    configuration=name,
                    repeat=repeat,
                    canonical_model=CANONICAL_MODEL,
                    endpoint="magpie",
                    verifier_config=VERIFIER_CFG,
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
    global VERIFIER_CFG
    if args.skip_verifier:
        from harbor.models.trial.config import VerifierConfig

        VERIFIER_CFG = VerifierConfig(disable=True)
        print("阶段1：验证器已禁用（只跑 agent 产出 patch）", flush=True)
    overrides = {}
    if args.tasks_root is not None:
        overrides["tasks_root"] = args.tasks_root
    if args.sample is not None:
        overrides["sample"] = args.sample
    paths = FormalPaths.from_env(**overrides)
    spec = json.loads(paths.sample.read_text(encoding="utf-8"))
    tasks = [t["task_id"] for t in spec["tasks"]]
    print(
        f"题集: {len(tasks)} 题；agent: {AGENTS}；repeats={args.repeats} concurrency={args.concurrency}",
        flush=True,
    )
    install_verifier_throttle(args.verifier_limit)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    agent_list = args.agents if args.agents else AGENTS
    for name in agent_list:
        rows = await run_agent(
            name, tasks, out_root, args.repeats, args.concurrency, args.skip_existing, paths
        )
        (out_root / f"{name}-summary.json").write_text(
            json.dumps({"agent": name, "n": len(rows)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print("全部完成", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--concurrency", type=int, default=12)
    p.add_argument("--verifier-limit", type=int, default=1)
    p.add_argument(
        "--skip-verifier", action="store_true", help="阶段1：跳过验证器，只跑 agent 产出 patch"
    )
    p.add_argument("--agents", nargs="+", default=None, help="只跑指定 agent")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--tasks-root", type=Path, default=None, help="默认取 SAYACODE_BENCH_TASKS_ROOT")
    p.add_argument(
        "--sample", type=Path, default=None, help="冻结题集，默认 studies/sample-40-final.json"
    )
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
