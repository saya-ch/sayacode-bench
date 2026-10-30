"""跑 holdout 全部可评测题（默认 20 题），保留镜像，供建立某模型的 L3 基线。

用法:
  python scripts/run_holdout.py --tasks-root <v2/tasks> --wheel <whl> \
      --requirements <req.txt> --profile <profile.json> --variant <variant.json> \
      --out <目录> [--repeats 1] [--model-label hy3] [--exclude-repos gravitational protonmail]

镜像需预先存在（可用 prewarm 脚本，保留不删）。串行执行便于按时间窗关联 served。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harbor.models.trial.config import AgentConfig, EnvironmentConfig  # noqa: E402

from sayacode_bench.connections import messages_endpoint  # noqa: E402
from sayacode_bench.execution import CANONICAL_MODEL, run_official_trial  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_summary import summary_text  # noqa: E402

SEL = ROOT / "studies" / "primary-selection-v1.json"


def build_agent(args: argparse.Namespace, work: Path) -> tuple[AgentConfig, EnvironmentConfig]:
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    upstream = messages_endpoint(profile["base_url"])
    profile["base_url"] = "http://saya-model-gateway:8080"
    private = work / "profile-private.json"
    private.write_text(json.dumps(profile), encoding="utf-8")
    agent = AgentConfig(
        import_path="sayacode_bench.adapter:SayacodeAgent",
        model_name=CANONICAL_MODEL,
        extra_allowed_hosts=["saya-model-gateway"],
        kwargs={
            "product_wheel": str(Path(args.wheel).resolve(strict=True)),
            "requirements_path": str(Path(args.requirements).resolve(strict=True)),
            "profile_path": str(private),
            "variant_path": str(Path(args.variant).resolve(strict=True)),
        },
    )
    env = EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": upstream},
    )
    return agent, env


async def main_async(args: argparse.Namespace) -> int:
    sel = json.loads(SEL.read_text(encoding="utf-8"))
    excluded = set(args.exclude_repos)
    tasks = []
    for t in sel["holdout"]:
        tid = t["task_id"]
        repo = tid.replace("instance_", "").split("__")[0]
        if repo in excluded:
            continue
        tasks.append(tid)

    print(summary_text(args.profile), flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    agent, env = build_agent(args, out)
    tasks_root = Path(args.tasks_root)
    rows = []
    sem = asyncio.Semaphore(max(1, args.concurrency))

    async def one(tid: str, repeat: int) -> None:
        # 并发受 Docker 内存限制：实测单容器约 0.8-1.5GB（配置 4GB 是上限）。
        async with sem:
            job = f"ho-{tid.replace('instance_', '')[:36]}-r{repeat}"
            job_dir = out / "jobs" / job
            if args.skip_existing and list(job_dir.glob("instance_*/verifier/reward.txt")):
                print(f"SKIP {tid[:48]} r{repeat}（已有结果）", flush=True)
                return
            # 旧 job 未收尾会让 Harbor 以身份不符拒绝；归档后重跑
            if job_dir.exists() and not list(job_dir.glob("instance_*/verifier/reward.txt")):
                target = out / "abandoned" / f"{job}-{int(__import__('time').time())}"
                target.parent.mkdir(parents=True, exist_ok=True)
                job_dir.rename(target)
                print(f"      归档旧 job -> {target.name}", flush=True)
            print(f"RUN {tid[:48]} r{repeat}", flush=True)
            try:
                rec = await run_official_trial(
                    tasks_root / tid, out / "jobs", job, agent, env,
                    configuration=args.model_label, repeat=repeat, endpoint="magpie",
                )
                reward, status = rec.get("original_reward"), rec.get("status")
            except Exception as exc:  # noqa: BLE001
                reward, status = None, f"exception:{type(exc).__name__}"
            rows.append({"task_id": tid, "repeat": repeat, "reward": reward, "status": status})
            print(f"    -> {status} reward={reward}", flush=True)

    await asyncio.gather(*[one(tid, r) for tid in tasks for r in range(1, args.repeats + 1)])

    valid = [r for r in rows if r["reward"] is not None]
    passed = sum(1 for r in valid if r["reward"] == 1.0)
    summary = {"model_label": args.model_label, "runs": len(rows),
               "with_reward": len(valid), "pass": passed}
    (out / "holdout-summary.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n=== {args.model_label} holdout 结果 ===")
    print(f"  有效 {len(valid)}/{len(rows)}，通过 {passed}（{passed/len(valid)*100:.1f}%）" if valid else "  无有效结果")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks-root", required=True)
    p.add_argument("--wheel", required=True)
    p.add_argument("--requirements", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--model-label", default="hy3")
    p.add_argument("--skip-existing", action="store_true", help="跳过已有验证结果的题（断点续跑）")
    p.add_argument("--concurrency", type=int, default=4, help="并发 trial 数；实测单容器约 0.8-1.5GB（配置 4GB 是上限），Docker 8GB 建议 4")
    p.add_argument("--exclude-repos", nargs="*", default=["gravitational", "protonmail"])
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
