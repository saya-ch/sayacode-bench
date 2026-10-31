"""Gold-patch 坏题筛查与三加一门禁。

门禁（三加一）：

1. ``oracle_pass``：参考解（OracleAgent）至少一次 reward=1。
2. ``oracle_stable``：参考解 ``--oracle-repeats`` 次全部 reward=1；默认只跑 1 次，
   报告里显式标注「单次不足」，正式门禁建议 2 次以上。
3. ``nop_fails``：不修改任何文件（NoOpAgent）时 reward=0；题本来就能过说明测试没有区分力。
   ``--nop`` 不传时该项记为 skipped，门禁结论不会冒充已检查。
4. ``complete``：每道题都有 oracle 结果且无异常。

用法::

    uv run --no-sync python scripts/gold_patch_check.py --tasks-root <v2/tasks> --out <目录> \\
        --oracle-repeats 2 --nop
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from harbor.models.trial.config import AgentConfig  # noqa: E402
from locked_agents import FormalPaths, env_cfg  # noqa: E402

from sayacode_bench.execution import run_official_trial  # noqa: E402

DEFAULT_SAMPLE = ROOT / "studies" / "sample-40-final.json"


async def main_async(args: argparse.Namespace) -> int:
    import subprocess

    subprocess.run(["docker", "network", "prune", "-f"], capture_output=True, timeout=120, check=False)

    sample = args.sample or DEFAULT_SAMPLE
    spec = json.loads(sample.read_text(encoding="utf-8"))
    tasks = [item["task_id"] for item in spec["tasks"]]
    tasks_root = Path(args.tasks_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = FormalPaths.from_env(tasks_root=tasks_root)
    sem = asyncio.Semaphore(max(1, args.concurrency))
    rows: list[dict] = []

    oracle = AgentConfig(name="oracle", model_name="oracle")
    nop = AgentConfig(import_path="locked_agents:NoOpAgent", model_name="nop")

    async def run_one(mode: str, tid: str, repeat: int, agent: AgentConfig) -> None:
        async with sem:
            job = f"{mode}-{tid.replace('instance_', '')[:34]}-r{repeat}"
            print(f"[{mode}] RUN {tid[:46]} r{repeat}", flush=True)
            try:
                record = await run_official_trial(
                    tasks_root / tid, out / "jobs", job, agent, env_cfg(paths),
                    configuration=mode, repeat=repeat, canonical_model=mode, endpoint="magpie",
                )
                reward, status = record.get("original_reward"), record.get("status")
            except Exception as exc:  # noqa: BLE001
                reward, status = None, f"exception:{type(exc).__name__}"
            rows.append(
                {"task_id": tid, "mode": mode, "repeat": repeat, "reward": reward, "status": status}
            )
            print(f"[{mode}]   -> {status} reward={reward}", flush=True)

    jobs = [
        run_one("gold", tid, repeat, oracle)
        for tid in tasks
        for repeat in range(1, args.oracle_repeats + 1)
    ]
    if args.nop:
        jobs.extend(run_one("nop", tid, 1, nop) for tid in tasks)
    await asyncio.gather(*jobs)

    gold_rows = [row for row in rows if row["mode"] == "gold"]
    nop_rows = [row for row in rows if row["mode"] == "nop"]
    by_task: dict[str, list[dict]] = {tid: [] for tid in tasks}
    for row in gold_rows:
        by_task[row["task_id"]].append(row)

    good = [tid for tid, values in by_task.items() if any(v["reward"] == 1.0 for v in values)]
    bad = [tid for tid, values in by_task.items() if values and all(v["reward"] == 0.0 for v in values)]
    suspicious = [tid for tid, values in by_task.items() if not values or any(v["reward"] is None for v in values)]
    unstable = [
        tid
        for tid, values in by_task.items()
        if len(values) == args.oracle_repeats and any(v["reward"] != 1.0 for v in values)
    ]
    nop_failed_cleanly = [row["task_id"] for row in nop_rows if row["reward"] == 0.0]
    nop_leaked = [row["task_id"] for row in nop_rows if row["reward"] != 0.0]

    gates = {
        "oracle_pass": {
            "passed": len(suspicious) == 0 and len(bad) == 0,
            "detail": f"好题 {len(good)}/{len(tasks)}，坏题 {len(bad)}，可疑 {len(suspicious)}",
        },
        "oracle_stable": {
            "passed": len(unstable) == 0,
            "oracle_repeats": args.oracle_repeats,
            "single_run_insufficient": args.oracle_repeats < 2,
            "detail": (
                f"全部 {args.oracle_repeats} 次通过" if not unstable else f"不稳定题 {len(unstable)}"
            ),
        },
        "nop_fails": {
            "passed": (len(nop_leaked) == 0) if args.nop else None,
            "checked": bool(args.nop),
            "detail": (
                "未启用（--nop 未传，门禁不能声称已检查）"
                if not args.nop
                else f"空 patch 干净失败 {len(nop_failed_cleanly)}/{len(tasks)}，泄漏 {len(nop_leaked)}"
            ),
        },
        "complete": {
            "passed": len(suspicious) == 0 and all(len(values) == args.oracle_repeats for values in by_task.values()),
            "detail": f"每题 {args.oracle_repeats} 次 oracle 结果齐全" if not suspicious else f"缺结果 {len(suspicious)}",
        },
    }
    required = [gates["oracle_pass"], gates["oracle_stable"], gates["complete"]]
    if args.nop:
        required.append(gates["nop_fails"])
    overall = all(bool(gate["passed"]) for gate in required)

    summary = {
        "sample": {"path": str(sample), "tasks": len(tasks)},
        "oracle_repeats": args.oracle_repeats,
        "nop_enabled": bool(args.nop),
        "gate": "pass" if overall else "fail",
        "gates": gates,
        "good": len(good),
        "bad": bad,
        "suspicious": suspicious,
        "unstable": unstable,
        "nop_leaked": nop_leaked,
        "rows": rows,
    }
    (out / "gold-report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("\n=== Gold patch 三加一门禁 ===")
    print(f"  oracle_repeats={args.oracle_repeats}" + ("（单次不足，正式门禁建议 ≥2）" if args.oracle_repeats < 2 else ""))
    for name, gate in gates.items():
        state = {True: "PASS", False: "FAIL", None: "SKIP"}[gate["passed"]]
        print(f"  [{state}] {name}: {gate['detail']}")
    print(f"  总门禁：{'通过' if overall else '未通过'}")
    if bad:
        print("  坏题清单：")
        for task in bad:
            print(f"    - {task}")
    if nop_leaked:
        print("  NOP 泄漏（无修复也能过）：")
        for task in nop_leaked:
            print(f"    - {task}")
    print(f"\n已写 {out / 'gold-report.json'}")
    return 0 if overall else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sample", type=Path, default=None, help="默认 studies/sample-40-final.json")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--oracle-repeats",
        type=int,
        default=1,
        help="参考解重复次数；默认 1 次并在报告中标明单次不足",
    )
    parser.add_argument("--nop", action="store_true", help="额外跑空 patch 门禁（无修复必须失败）")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
