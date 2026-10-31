"""阶段 2：统一验证。对阶段 1 产出的 patch 用 PatchReplayAgent 在干净沙箱重放验证。

空 patch 不再静默 ``return``：写入 ``verifier/terminal.json``（``skipped_empty_patch``）作为显式终态，
第二次运行时 ``--skip-existing`` 判据只认「reward 或 terminal 标记」，不会永久 pending。

用法::

    uv run --no-sync python scripts/verify_patches.py --out C:\\sb\\hard\\formal-240 \\
        --tasks-root <v2/tasks> --agents sayacode mini-swe codex --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from harbor.models.trial.config import AgentConfig  # noqa: E402
from locked_agents import FormalPaths, env_cfg  # noqa: E402

from sayacode_bench.execution import run_official_trial  # noqa: E402

TERMINAL_EMPTY_PATCH = "skipped_empty_patch"


def _inner_dir(job: Path) -> Path | None:
    return next(
        (child for child in sorted(job.iterdir()) if child.is_dir() and child.name.startswith("instance_")),
        None,
    )


def _task_of(inner: Path) -> str | None:
    result = inner / "result.json"
    if not result.is_file():
        return None
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = payload.get("task_name")
    if isinstance(name, str) and name:
        return name.split("/")[-1]
    identifier = payload.get("task_id")
    if isinstance(identifier, dict):
        path = identifier.get("path")
        if isinstance(path, str) and path:
            return Path(path).name
    return None


def record_empty_patch(inner: Path, patch_bytes: int) -> Path:
    """把空 patch 记成显式终态，而不是留下无法解释的 pending。"""
    verifier = inner / "verifier"
    verifier.mkdir(parents=True, exist_ok=True)
    terminal = verifier / "terminal.json"
    terminal.write_text(
        json.dumps(
            {
                "status": TERMINAL_EMPTY_PATCH,
                "reward": 0.0,
                "patch_bytes": patch_bytes,
                "reason": "agent/model.patch 为空，未进入验证器",
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return terminal


def collect_pending(jobs: Path) -> list[tuple[str, str, int, Path]]:
    """待验证 = 无 reward、无终态标记、但已有 patch 文件的 trial。"""
    pending: list[tuple[str, str, int, Path]] = []
    for job in sorted(jobs.iterdir()):
        if not job.is_dir():
            continue
        inner = _inner_dir(job)
        if inner is None:
            continue
        if (inner / "verifier" / "reward.txt").is_file():
            continue
        if (inner / "verifier" / "terminal.json").is_file():
            continue
        patch = inner / "agent" / "model.patch"
        if not patch.is_file():
            continue
        task = _task_of(inner)
        if task:
            pending.append((job.name, task, patch.stat().st_size, inner))
    return pending


async def main_async(args: argparse.Namespace) -> int:
    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False)
    paths = FormalPaths.from_env(tasks_root=args.tasks_root) if args.tasks_root else FormalPaths.from_env()
    out_root = Path(args.out)
    sem = asyncio.Semaphore(max(1, args.concurrency))
    total = 0

    for name in args.agents:
        jobs = out_root / name / "jobs"
        if not jobs.is_dir():
            print(f"[{name}] 无 jobs", flush=True)
            continue
        pending = collect_pending(jobs)
        print(f"[{name}] 待验证 {len(pending)} 个", flush=True)
        verify_dir = out_root / name / "verify"

        async def one(job_name: str, task: str, patch_bytes: int, inner: Path) -> None:
            async with sem:
                if patch_bytes == 0:
                    terminal = record_empty_patch(inner, patch_bytes)
                    print(
                        f"[{name}] {task[:40]} 空 patch -> 记录终态 {TERMINAL_EMPTY_PATCH}",
                        flush=True,
                    )
                    print(f"[{name}]   终态文件 {terminal}", flush=True)
                    return
                vjob = f"verify-{job_name}"
                print(f"[{name}] VERIFY {task[:44]}", flush=True)
                try:
                    record = await run_official_trial(
                        paths.tasks_root / task,
                        verify_dir / "jobs",
                        vjob,
                        AgentConfig(
                            import_path="locked_agents:PatchReplayAgent",
                            model_name="replay",
                            kwargs={"source_job": str(jobs / job_name)},
                        ),
                        env_cfg(paths),
                        configuration="verify",
                        repeat=1,
                        canonical_model="replay",
                        endpoint="magpie",
                    )
                    print(
                        f"[{name}]   -> {record.get('status')} reward={record.get('original_reward')}",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[{name}]   -> exception {type(exc).__name__}: {str(exc)[:100]}", flush=True)

        await asyncio.gather(*[one(job, task, size, inner) for job, task, size, inner in pending])
        total += len(pending)

    print(f"阶段2 完成，共处理 {total}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--agents", nargs="+", default=["sayacode", "mini-swe", "codex"])
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--tasks-root", type=Path, default=None, help="默认取 SAYACODE_BENCH_TASKS_ROOT")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
