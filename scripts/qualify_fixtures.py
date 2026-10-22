"""在正式模型运行前，以固定参考解/空解门禁构建环境资格子集。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from harbor.models.trial.config import AgentConfig, EnvironmentConfig

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.execution import run_official_trial
from sayacode_bench.gates import TASK_IDENTITIES
from sayacode_bench.selection import select_tasks
from sayacode_bench.sources import SOURCES, TaskRecord, build_catalog, fetch_source

MIN_DISK_HEADROOM_BYTES = 12 * 1024**3


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def runtime_confirmed(record: dict[str, Any]) -> bool:
    value = record.get("runtime_identity")
    return (
        isinstance(value, dict)
        and value.get("available") is True
        and all(
            isinstance(value.get(key), str) and value[key]
            for key in ("image_id", "architecture", "os")
        )
    )


def grade_qualification(
    task: TaskRecord, oracle: list[dict[str, Any]], nop: dict[str, Any], repeats: int
) -> dict[str, Any]:
    reasons = []
    if len(oracle) != repeats or any(
        row.get("status") != "completed"
        or row.get("verified") is not True
        or row.get("success") is not True
        or row.get("original_reward") != 1
        for row in oracle
    ):
        reasons.append("reference_not_accepted_in_every_fixed_trial")
    if (
        nop.get("status") != "completed"
        or nop.get("verified") is not True
        or nop.get("success") is not False
        or nop.get("original_reward") != 0
    ):
        reasons.append("empty_solution_not_confirmed_rejected")
    records = [*oracle, nop]
    runtime_ready = all(runtime_confirmed(row) for row in records)
    if not runtime_ready:
        reasons.append("native_runtime_evidence_unconfirmed")
    runtime_keys = {
        digest(
            {
                key: row["runtime_identity"].get(key)
                for key in ("image_id", "architecture", "os", "docker_limits", "requested")
            }
        )
        for row in records
        if runtime_confirmed(row)
    }
    if len(runtime_keys) != 1:
        reasons.append("native_runtime_identity_changed")
    return {
        "task_id": task.task_id,
        "leakage_group": task.leakage_group,
        "task_identity": digest(task.public_dict()),
        **{name: getattr(task, name) for name in TASK_IDENTITIES},
        "oracle": oracle[0] if oracle else None,
        "oracle_trials": oracle,
        "nop": nop,
        "oracle_repeats": repeats,
        "runtime_confirmed": runtime_ready,
        "passed": not reasons,
        "reasons": reasons,
    }


def select_again(
    catalog: list[TaskRecord], initial: dict[str, Any], rejected: set[str]
) -> dict[str, Any]:
    rules = initial["rules"]
    selected: dict[str, Any] = select_tasks(
        catalog,
        dev_count=len(initial["dev"]),
        holdout_count=len(initial["holdout"]),
        seed=initial["seed"],
        max_memory_mb=rules["max_memory_mb"],
        preferred_languages=tuple(rules.get("preferred_languages", ["python"])),
        languages=tuple(rules["languages"]) if rules.get("languages") is not None else None,
        categories=tuple(rules["categories"]) if rules.get("categories") is not None else None,
        max_agent_timeout_sec=rules.get("max_agent_timeout_sec"),
        excluded_leakage_groups=sorted(set(rules.get("excluded_leakage_groups", [])) | rejected),
    ).public_dict()
    if selected["catalog_sha256"] != initial["catalog_sha256"]:
        raise ValueError("完整候选池与初始选择身份不同")
    groups = {task.task_id: task.leakage_group for task in catalog}
    for row in selected["exclusions"]:
        if groups[row["task_id"]] in rejected:
            row["reason"] = "fixture_qualification_failed"
    selected["rules"]["fixture_gate"] = {
        "calibration_excluded_leakage_groups": rules.get("excluded_leakage_groups", []),
        "rejected_leakage_groups": sorted(rejected),
        "replacement": "rerun original seeded selector on full catalog; preserve strata rules",
    }
    return selected


async def qualify_one(
    task: TaskRecord,
    snapshot: Any,
    output: Path,
    oracle_repeats: int,
    environment: EnvironmentConfig,
) -> dict[str, Any]:
    key = digest({"benchmark": task.benchmark, "task_id": task.task_id})[:20]
    directory = output / "qualifications" / key
    identity = digest(task.public_dict())
    result_path = directory / "qualification.json"
    if result_path.is_file():
        saved: dict[str, Any] = read_json(result_path)
        if saved.get("task_identity") != identity or saved.get("oracle_repeats") != oracle_repeats:
            raise ValueError("已保存资格记录属于不同任务或门禁规则")
        return saved
    records = []
    for name, repeat in [
        *(("oracle", index) for index in range(1, oracle_repeats + 1)),
        ("nop", 1),
    ]:
        path = directory / f"{name}-{repeat}.json"
        if path.is_file():
            saved = read_json(path)
            if saved.get("task_identity") != identity:
                raise ValueError("资格子试验的任务身份不一致")
            record = saved["record"]
        else:
            print(
                f"  {name} {repeat}/{oracle_repeats if name == 'oracle' else 1} {task.task_id}",
                flush=True,
            )
            try:
                record = await run_official_trial(
                    snapshot.tasks_path / task.task_id,
                    output / "jobs",
                    f"fixture-{key}-{name}-{repeat}",
                    AgentConfig(name=name),
                    environment,
                    configuration=name,
                    repeat=repeat,
                    endpoint="local",
                )
            except Exception as exc:
                # 保留无法确认的原生 job；不以新名字悄悄补跑这一轮。
                record = {
                    "task_id": task.task_id,
                    "status": "qualification_error",
                    "verified": False,
                    "success": None,
                    "original_reward": None,
                    "error_type": type(exc).__name__,
                }
            write_json(path, {"task_identity": identity, "record": record}, exclusive=True)
        records.append(record)
    result = grade_qualification(task, records[:-1], records[-1], oracle_repeats)
    write_json(result_path, result, exclusive=True)
    return result


def save_outcome(
    output: Path,
    initial: dict[str, Any],
    current: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, Any]:
    tasks = [*current["dev"], *current["holdout"]]
    selected_receipts = [receipts[task["task_id"]] for task in tasks if task["task_id"] in receipts]
    summary = {
        "benchmark": tasks[0]["benchmark"],
        "revision": tasks[0]["revision"],
        "complete": complete,
        "passed": complete and all(row["passed"] for row in selected_receipts),
        "tasks": selected_receipts,
        "qualification": {
            "reason": reason,
            "checked_candidates": len(receipts),
            "qualified_candidates": sum(row["passed"] for row in receipts.values()),
            "rejected": [
                {
                    "task_id": row["task_id"],
                    "leakage_group": row["leakage_group"],
                    "reasons": row["reasons"],
                }
                for row in receipts.values()
                if not row["passed"]
            ],
            "planned_dev": len(initial["dev"]),
            "planned_holdout": len(initial["holdout"]),
            "scope": "本地环境资格子集，不是原始公开基准均匀样本或全榜成绩",
        },
    }
    write_json(output / "selection.json", current)
    write_json(output / "sanity.json", summary)
    return summary


async def qualify(
    selection_path: Path,
    cache: Path,
    output: Path,
    *,
    oracle_repeats: int = 3,
    max_candidates: int = 64,
) -> dict[str, Any]:
    """固定原选择规则与资格次数，失败只改变资格池，不改变评分。"""
    if type(oracle_repeats) is not int or oracle_repeats != 3:
        raise ValueError("本轮预注册固定三次 oracle")
    initial = read_json(selection_path)
    selected_tasks = [*initial.get("dev", []), *initial.get("holdout", [])]
    if not initial.get("dev") or not initial.get("holdout"):
        raise ValueError("需要非空开发与最终候选集合")
    sources = {(task["benchmark"], task["revision"]) for task in selected_tasks}
    if len(sources) != 1:
        raise ValueError("一次资格批次只能使用一个固定基准")
    if type(max_candidates) is not int or max_candidates < len(selected_tasks):
        raise ValueError("资格候选预算不能小于目标任务总数")
    benchmark, revision = next(iter(sources))
    snapshot = fetch_source(SOURCES[benchmark], cache)
    if snapshot.spec.revision != revision:
        raise ValueError("初始候选与固定基准版本不同")
    catalog = build_catalog(snapshot)
    indexed = {task.task_id: task for task in catalog}
    proposal = select_again(catalog, initial, set())
    for split in ("dev", "holdout"):
        if proposal[split] != initial[split]:
            raise ValueError("原 seed/rules 无法重建初始选择，禁止猜测替补")
    output, cache = output.resolve(), cache.resolve()
    if output.is_relative_to(cache) or cache.is_relative_to(output):
        raise ValueError("资格结果不能覆盖源缓存或其祖先")
    plan = {
        "schema_version": 1,
        "phase": "fixture_qualification",
        "benchmark": benchmark,
        "revision": revision,
        "original_catalog_sha256": initial["catalog_sha256"],
        "initial_selection_sha256": file_sha256(selection_path),
        "script_sha256": file_sha256(Path(__file__)),
        "implementation": implementation_identity(),
        "oracle_repeats": oracle_repeats,
        "nop_repeats": 1,
        "max_candidates": max_candidates,
        "min_disk_headroom_bytes": MIN_DISK_HEADROOM_BYTES,
        "seed": initial["seed"],
        "rules": initial["rules"],
        "dev_count": len(initial["dev"]),
        "holdout_count": len(initial["holdout"]),
        "replacement": "qualify all tasks in a selection version, then reselect with every rejected fix group excluded",
        "score_policy": "keep all official scores; never retry until success or overwrite failures",
    }
    if output.exists():
        if not (output / "plan.json").is_file() or read_json(output / "plan.json") != plan:
            raise ValueError("已有目录不是完全相同的资格计划，拒绝覆盖")
        if (output / "sanity.json").is_file() and read_json(output / "sanity.json").get(
            "complete"
        ) is True:
            return dict(read_json(output / "sanity.json"))
    else:
        output.mkdir(parents=True)
        write_json(output / "plan.json", plan, exclusive=True)
        with (output / "initial-selection.json").open("xb") as stream:
            stream.write(selection_path.read_bytes())
    receipts = {}
    for path in sorted((output / "qualifications").glob("*/qualification.json")):
        row = read_json(path)
        task = indexed.get(row.get("task_id"))
        if task is None or row.get("task_identity") != digest(task.public_dict()):
            raise ValueError("恢复资格记录的任务身份不一致")
        receipts[task.task_id] = row
    versions = sorted((output / "selections").glob("selection-*.json"))
    current = read_json(versions[-1]) if versions else proposal
    if not versions:
        write_json(output / "selections" / "selection-000.json", current, exclusive=True)
        versions = [output / "selections" / "selection-000.json"]
    environment = EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": "http://host.docker.internal:8787/v1/messages"},
    )
    while True:
        tasks = [*current["dev"], *current["holdout"]]
        for task_data in tasks:
            task_id = task_data["task_id"]
            if task_id in receipts:
                continue
            if len(receipts) >= max_candidates:
                return save_outcome(
                    output,
                    initial,
                    current,
                    receipts,
                    complete=False,
                    reason="candidate_budget_exhausted",
                )
            if shutil.disk_usage(output.anchor).free < MIN_DISK_HEADROOM_BYTES:
                return save_outcome(
                    output,
                    initial,
                    current,
                    receipts,
                    complete=False,
                    reason="insufficient_disk_headroom",
                )
            write_json(
                output / "progress.json",
                {"checked_candidates": len(receipts), "active_task": task_id},
            )
            receipts[task_id] = await qualify_one(
                indexed[task_id], snapshot, output, oracle_repeats, environment
            )
            save_outcome(
                output,
                initial,
                current,
                receipts,
                complete=False,
                reason="qualification_in_progress",
            )
        if all(receipts[task["task_id"]]["passed"] for task in tasks):
            return save_outcome(output, initial, current, receipts, complete=True, reason=None)
        rejected = {row["leakage_group"] for row in receipts.values() if not row["passed"]}
        try:
            current = select_again(catalog, initial, rejected)
        except ValueError:
            return save_outcome(
                output, initial, current, receipts, complete=False, reason="eligible_pool_exhausted"
            )
        path = output / "selections" / f"selection-{len(versions):03}.json"
        write_json(path, current, exclusive=True)
        versions.append(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--oracle-repeats", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=64)
    args = parser.parse_args()
    result = asyncio.run(
        qualify(
            args.selection,
            args.cache,
            args.output,
            oracle_repeats=args.oracle_repeats,
            max_candidates=args.max_candidates,
        )
    )
    print(
        json.dumps(
            {key: result[key] for key in ("benchmark", "complete", "passed", "qualification")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
