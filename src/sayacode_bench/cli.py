"""公开源、门禁、冻结、执行和报告的薄命令入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from harbor.models.trial.config import AgentConfig, EnvironmentConfig

from .analysis import select_development_candidate
from .artifacts import file_sha256, implementation_identity, read_json, report_manifest, write_json
from .connections import CANONICAL_MODEL
from .execution import run_official_trial
from .gates import TASK_IDENTITIES, validate_preflight
from .locking import lock_candidate, validate_candidate_receipt
from .selection import select_tasks, write_manifest
from .sources import SOURCES, build_catalog, fetch_source
from .study import freeze_paid_budget, phase_summary, run_phase


def _mapping(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or name in result:
            raise ValueError("参数必须是唯一的 名称=路径")
        result[name] = Path(path).resolve(strict=True)
    return result


async def sanity(manifest_path: Path, cache: Path, output: Path) -> dict[str, Any]:
    """只用官方 oracle/nop 校验选中题目，完全不调用模型。"""
    manifest = read_json(manifest_path)
    if output.resolve().is_relative_to(cache.resolve()) or cache.resolve().is_relative_to(
        output.resolve()
    ):
        raise ValueError("门禁结果不能写入公开源缓存或其祖先目录")
    tasks = manifest.get("tasks") or [*manifest.get("dev", []), *manifest.get("holdout", [])]
    if not tasks or len({(task["benchmark"], task["revision"]) for task in tasks}) != 1:
        raise ValueError("一次门禁必须对应同一固定基准的非空任务集")
    benchmark = tasks[0]["benchmark"]
    snapshot = fetch_source(SOURCES[benchmark], cache)
    if tasks[0]["revision"] != snapshot.spec.revision:
        raise ValueError("门禁任务来源与固定快照不同")
    results = []
    environment = EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": "http://127.0.0.1:9/v1/messages"},
    )
    for index, task in enumerate(tasks, 1):
        results_for_task = {}
        for agent_name in ("oracle", "nop"):
            print(f"[{index}/{len(tasks)}] {agent_name} {task['task_id']}", flush=True)
            record = await run_official_trial(
                snapshot.tasks_path / task["task_id"],
                output / "jobs",
                f"sanity-{index:04}-{agent_name}",
                AgentConfig(name=agent_name),
                environment,
                configuration=agent_name,
            )
            results_for_task[agent_name] = record
        results.append(
            {
                "task_id": task["task_id"],
                **{key: task[key] for key in TASK_IDENTITIES},
                **results_for_task,
                "passed": results_for_task["oracle"]["success"] is True
                and results_for_task["nop"]["success"] is False
                and results_for_task["nop"]["verified"] is True,
            }
        )
        write_json(
            output / "sanity.json",
            {
                "benchmark": benchmark,
                "revision": snapshot.spec.revision,
                "tasks": results,
                "complete": len(results) == len(tasks),
                "passed": all(row["passed"] for row in results),
            },
        )
    return read_json(output / "sanity.json")


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    selection = read_json(args.selection)
    variants, connections = _mapping(args.variant), _mapping(args.connection)
    if "baseline" not in variants or args.repeats < 1 or args.reported_token_limit < 1:
        raise ValueError("必须声明基线、正重复数和正用量阈值")
    tasks = selection["dev" if args.phase == "dev" else "holdout"]
    gate = read_json(args.sanity)
    probe = read_json(args.network_probe)
    validate_preflight(
        gate, probe, benchmark=tasks[0]["benchmark"], revision=tasks[0]["revision"], tasks=tasks
    )
    if args.phase == "holdout" and len(variants) != 2:
        raise ValueError("最终验收必须是基线和一个已锁定候选")
    profiles = {
        label: {key: value for key, value in read_json(path).items() if key != "api_key"}
        for label, path in connections.items()
    }
    manifest = {
        "schema_version": 1,
        "phase": args.phase,
        "frozen": True,
        "runtime_evidence_required": True,
        "qualified_runtime_identities": {
            row["task_id"]: row.get("oracle", {}).get("runtime_identity")
            for row in gate["tasks"]
            if row["task_id"] in {task["task_id"] for task in tasks}
        },
        "canonical_model": CANONICAL_MODEL,
        "benchmark": tasks[0]["benchmark"],
        "revision": tasks[0]["revision"],
        "seed": args.seed,
        "configurations": list(variants),
        "baseline": "baseline",
        "candidate": next((name for name in variants if name != "baseline"), None)
        if args.phase == "holdout"
        else None,
        "repeats": args.repeats,
        "connections": list(connections),
        "connection_profiles": profiles,
        "tasks": tasks,
        "reported_token_limit": args.reported_token_limit,
        "preflight_passed": True,
        "preflight": {
            "sanity_sha256": file_sha256(args.sanity),
            "network_probe_sha256": file_sha256(args.network_probe),
        },
        "selection_sha256": file_sha256(args.selection),
        "artifacts": {
            "product_wheel": file_sha256(args.wheel),
            "requirements": file_sha256(args.requirements),
            "variants": {name: file_sha256(path) for name, path in variants.items()},
        },
        "implementation": implementation_identity(),
        "validity_issues": [],
        "scope": "固定公开子集和本地网络实现，不宣称官方完整榜单成绩",
    }
    if any(
        not isinstance(identity, dict)
        or identity.get("available") is not True
        or not all(identity.get(key) for key in ("image_id", "architecture", "os"))
        for identity in manifest["qualified_runtime_identities"].values()
    ):
        raise ValueError("评分门禁缺少实际镜像和平台身份，请重新执行真实门禁")
    paid_budget = freeze_paid_budget(
        limit_cny=getattr(args, "paid_limit_cny", None),
        stop_fraction=getattr(args, "paid_stop_fraction", 0.8),
        price_snapshot=getattr(args, "paid_price_snapshot", None),
        prior_records=getattr(args, "prior_records", None),
        paid_endpoints=getattr(args, "paid_endpoint", None),
    )
    if paid_budget is not None:
        manifest["paid_budget"] = paid_budget
    if args.phase in {"holdout", "validation"}:
        if args.candidate_lock is None:
            raise ValueError("最终阶段必须先签收完整开发结果和候选")
        receipt = validate_candidate_receipt(args.candidate_lock, manifest, variant_paths=variants)
        manifest["candidate_receipt"] = {
            "path": str(args.candidate_lock.resolve()),
            "sha256": receipt["receipt_sha256"],
        }
    write_json(args.output, manifest, exclusive=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="检查 Docker API，不调用模型")
    doctor.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare", help="固定公开源并冻结抽样名单")
    prepare.add_argument("--benchmark", choices=list(SOURCES), required=True)
    prepare.add_argument("--cache", type=Path, required=True)
    prepare.add_argument("--dev", type=int, required=True)
    prepare.add_argument("--holdout", type=int, required=True)
    prepare.add_argument("--seed", required=True)
    prepare.add_argument("--language", action="append")
    prepare.add_argument(
        "--category", action="append", help="预先声明任务类别，可重复；不声明则不限类别"
    )
    prepare.add_argument(
        "--max-agent-timeout-sec",
        type=float,
        help="仅选择官方 Agent 时间预算不超过此值的任务，不修改原值",
    )
    prepare.add_argument(
        "--exclude-leakage-group",
        action="append",
        default=[],
        help="排除已曝光的修复组，可重复声明",
    )
    prepare.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("sanity", help="运行官方参考解与空解")
    for sub in (preflight,):
        sub.add_argument("--manifest", type=Path, required=True)
        sub.add_argument("--cache", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
    frozen = commands.add_parser("freeze", help="门禁通过后冻结正式研究")
    frozen.add_argument("--phase", choices=("dev", "holdout", "validation"), required=True)
    frozen.add_argument("--selection", type=Path, required=True)
    frozen.add_argument("--sanity", type=Path, required=True)
    frozen.add_argument("--network-probe", type=Path, required=True)
    frozen.add_argument("--candidate-lock", type=Path)
    frozen.add_argument("--seed", required=True)
    frozen.add_argument("--repeats", type=int, default=2)
    frozen.add_argument("--reported-token-limit", type=int, required=True)
    frozen.add_argument(
        "--paid-limit-cny",
        type=float,
        help="显式授权的跨阶段付费估算预算；不声明则不启用人民币门禁",
    )
    frozen.add_argument("--paid-stop-fraction", type=float, default=0.8)
    frozen.add_argument("--paid-price-snapshot", type=Path)
    frozen.add_argument("--paid-endpoint", action="append", help="按次估价的连接别名，可重复声明")
    frozen.add_argument(
        "--prior-records",
        type=Path,
        action="append",
        default=[],
        help="先前阶段的全部原始记录文件，路径和内容哈希会冻结",
    )
    frozen.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run", help="执行冻结的配对研究")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--cache", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument(
        "--private-home", type=Path, default=Path.home() / ".config" / "sayacode-bench"
    )
    for sub in (frozen, run):
        sub.add_argument("--variant", action="append", required=True, metavar="名称=文件")
        sub.add_argument("--connection", action="append", required=True, metavar="别名=私有文件")
        sub.add_argument("--wheel", type=Path, required=True)
        sub.add_argument("--requirements", type=Path, required=True)
    report = commands.add_parser("report", help="从原始结果只读汇总或开发选型")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--records", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--select-candidate", action="store_true")
    locked = commands.add_parser("lock-candidate", help="完整开发比较后签收候选和源码身份")
    locked.add_argument("--manifest", type=Path, required=True)
    locked.add_argument("--records", type=Path, required=True)
    locked.add_argument("--variant", action="append", required=True, metavar="名称=文件")
    locked.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "doctor":
            try:
                result = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                value = {
                    "docker_api_ready": result.returncode == 0,
                    "server_version": result.stdout.strip() if result.returncode == 0 else None,
                    "return_code": result.returncode,
                }
            except (OSError, subprocess.TimeoutExpired) as exc:
                value = {"docker_api_ready": False, "error_type": type(exc).__name__}
            write_json(args.output, value)
        elif args.command == "prepare":
            source = fetch_source(SOURCES[args.benchmark], args.cache)
            selection = select_tasks(
                build_catalog(source),
                dev_count=args.dev,
                holdout_count=args.holdout,
                seed=args.seed,
                languages=tuple(args.language) if args.language else None,
                categories=tuple(args.category) if args.category else None,
                max_agent_timeout_sec=args.max_agent_timeout_sec,
                excluded_leakage_groups=tuple(args.exclude_leakage_group),
            )
            write_manifest(selection, args.output)
            value = {
                "dev": len(selection.dev),
                "holdout": len(selection.holdout),
                "eligible": selection.eligible_count,
            }
        elif args.command == "sanity":
            value = asyncio.run(sanity(args.manifest, args.cache, args.output))
        elif args.command == "freeze":
            value = freeze(args)
        elif args.command == "run":
            value = asyncio.run(
                run_phase(
                    args.manifest,
                    args.output,
                    args.cache,
                    args.wheel,
                    args.requirements,
                    _mapping(args.variant),
                    _mapping(args.connection),
                    args.private_home,
                )
            )
        elif args.command == "lock-candidate":
            value = lock_candidate(args.manifest, args.records, _mapping(args.variant), args.output)
        else:
            manifest = report_manifest(read_json(args.manifest), args.records.parent)
            records = [
                json.loads(line)
                for line in args.records.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            value = (select_development_candidate if args.select_candidate else phase_summary)(
                manifest, records
            )
            write_json(args.output, value)
        print(json.dumps({"command": args.command, "output": str(args.output)}, ensure_ascii=False))
        if args.command == "doctor" and not value.get("docker_api_ready"):
            return 1
        if args.command == "sanity" and (not value.get("passed") or not value.get("complete")):
            return 1
        if args.command == "run" and (value.get("missing_trials") or value.get("validity_issues")):
            return 1
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, KeyError) as exc:
        # 只输出类型；任何含私有连接的底层错误正文都留在用户本机受限目录。
        print(json.dumps({"command": args.command, "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
