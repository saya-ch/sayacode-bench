"""在正式模型运行前，以固定参考解/空解门禁构建环境资格子集。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from harbor.models.trial.config import AgentConfig, EnvironmentConfig
from harbor.models.trial.result import TrialResult

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.execution import normalize_trial_result, run_official_trial
from sayacode_bench.gates import TASK_IDENTITIES
from sayacode_bench.resources import compare_runtimes, resource_status
from sayacode_bench.selection import select_tasks
from sayacode_bench.sources import SOURCES, TaskRecord, build_catalog, fetch_source

MIN_DISK_HEADROOM_BYTES = 12 * 1024**3


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def control_issues(task: TaskRecord, record: dict[str, Any], name: str, repeat: int) -> list[str]:
    """资格只接受已确认的原生控制试验；执行故障不能当作 fixture 失败。"""
    issues = []
    if (
        record.get("task_id") != task.task_id
        or record.get("configuration") != name
        or type(record.get("repeat")) is not int
        or record["repeat"] != repeat
        or record.get("record_complete") is not True
        or record.get("status") != "completed"
        or record.get("verified") is not True
        or type(record.get("original_reward")) not in (int, float)
        or record["original_reward"] not in (0, 1)
        or record.get("success") is not (record.get("original_reward") == 1)
        or not isinstance(record.get("request_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", record["request_sha256"]) is None
    ):
        issues.append("native_control_unconfirmed")
    runtime = record.get("runtime_identity")
    if resource_status(runtime, task.environment) is not True or any(
        value is not True for value in compare_runtimes(runtime, runtime, task.environment).values()
    ):
        issues.append("native_runtime_evidence_unconfirmed")
    try:
        references = {}
        for field in ("raw_trial_result", "runtime"):
            reference = record[field]
            path = Path(reference["path"]).resolve(strict=True)
            if not path.is_file() or file_sha256(path) != reference["sha256"]:
                raise ValueError("原生控制工件身份变化")
            references[field] = path
        native_path = references["raw_trial_result"]
        if (
            native_path.name != "result.json"
            or native_path.parent.parent != Path(record["job_dir"]).resolve()
            or references["runtime"] != native_path.parent / "runtime.json"
        ):
            raise ValueError("原生控制来源目录变化")
        trial = TrialResult.model_validate(read_json(native_path))
        if (
            trial.config.agent.name != name
            or trial.config.task.path.name != task.task_id
            or trial.started_at is None
            or trial.finished_at is None
            or trial.exception_info is not None
        ):
            raise ValueError("原生控制任务或 Agent 不一致")
        native = normalize_trial_result(
            trial, native_path.parent, configuration=name, repeat=repeat, endpoint="local"
        )
        if any(
            native.get(field) != record.get(field)
            for field in (
                "task_id",
                "status",
                "verified",
                "success",
                "original_reward",
                "record_complete",
                "runtime_identity",
                "runtime",
                "raw_trial_result",
            )
        ):
            raise ValueError("原生控制事实与保存记录不同")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        issues.append("native_control_evidence_unconfirmed")
    return issues


def grade_qualification(
    task: TaskRecord, oracle: list[dict[str, Any]], nop: dict[str, Any] | None, repeats: int
) -> dict[str, Any]:
    records = [*oracle, *([nop] if nop is not None else [])]
    issues = [
        issue
        for name, repeat, row in [
            *(("oracle", index, row) for index, row in enumerate(oracle, 1)),
            *(([("nop", 1, nop)]) if nop is not None else []),
        ]
        for issue in control_issues(task, row, name, repeat)
    ]
    if records and any(
        value is not True
        for row in records[1:]
        for value in compare_runtimes(
            records[0].get("runtime_identity"), row.get("runtime_identity"), task.environment
        ).values()
    ):
        issues.append("native_runtime_identity_changed")
    for field in ("request_sha256", "raw_trial_result"):
        identities = [
            (row[field].get("sha256") if isinstance(row.get(field), dict) else None)
            if field == "raw_trial_result"
            else row.get(field)
            for row in records
        ]
        if len({str(value) for value in identities}) != len(records):
            issues.append("native_controls_not_independent")
    complete = len(oracle) == repeats and nop is not None and not issues
    reasons = list(issues)
    if len(oracle) != repeats or nop is None:
        reasons.append("fixed_controls_incomplete")
    if complete:
        assert nop is not None
        if any(row["original_reward"] != 1 for row in oracle):
            reasons.append("reference_not_accepted_in_every_fixed_trial")
        if nop["original_reward"] != 0:
            reasons.append("empty_solution_not_confirmed_rejected")
    return {
        "task_id": task.task_id,
        "leakage_group": task.leakage_group,
        "task_identity": digest(task.public_dict()),
        **{name: getattr(task, name) for name in TASK_IDENTITIES},
        "oracle": oracle[0] if oracle else None,
        "oracle_trials": oracle,
        "nop": nop,
        "oracle_repeats": repeats,
        "runtime_confirmed": not any("runtime" in issue for issue in issues) and bool(records),
        "complete": complete,
        "continuation_allowed": not issues,
        "passed": complete and not reasons,
        "reasons": sorted(set(reasons)),
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
    *,
    max_new_controls: int | None = None,
) -> dict[str, Any]:
    key = digest({"benchmark": task.benchmark, "task_id": task.task_id})[:20]
    directory = output / "qualifications" / key
    identity = digest(task.public_dict())
    result_path = directory / "qualification.json"
    if result_path.is_file():
        saved: dict[str, Any] = read_json(result_path)
        if saved.get("task_identity") != identity or saved.get("oracle_repeats") != oracle_repeats:
            raise ValueError("已保存资格记录属于不同任务或门禁规则")
    oracle: list[dict[str, Any]] = []
    nop = None
    new_controls = 0

    def finish(reason: str | None = None) -> dict[str, Any]:
        result = grade_qualification(task, oracle, nop, oracle_repeats)
        result["stop_reason"] = reason
        write_json(result_path, result)
        return {**result, "new_controls_executed": new_controls}

    for name, repeat in [
        *(("oracle", index) for index in range(1, oracle_repeats + 1)),
        ("nop", 1),
    ]:
        path = directory / f"{name}-{repeat}.json"
        job_name = f"fixture-{key}-{name}-{repeat}"
        job_dir = output / "jobs" / job_name
        attempt_path = directory / f"{name}-{repeat}.attempt.json"
        attempt = {
            "task_identity": identity,
            "configuration": name,
            "repeat": repeat,
            "job_dir": str(job_dir),
            "environment": environment.model_dump(mode="json"),
        }
        if path.is_file():
            saved = read_json(path)
            if saved.get("task_identity") != identity or saved.get("control") != attempt:
                raise ValueError("资格子试验的任务身份不一致")
            record = saved["record"]
            if not isinstance(record, dict) or record.get("job_dir") != str(job_dir):
                raise ValueError("资格子试验的固定 job 来源不一致")
        else:
            if attempt_path.exists() and read_json(attempt_path) != attempt:
                raise ValueError("资格控制尝试身份已变化")
            if attempt_path.exists() or job_dir.exists():
                # 已存在的原生执行只读恢复完整 normalized；未知现场绝不重新调用 Job。
                normalized = job_dir / "normalized.json"
                record = (
                    read_json(normalized)
                    if attempt_path.is_file() and normalized.is_file()
                    else {
                        "task_id": task.task_id,
                        "configuration": name,
                        "repeat": repeat,
                        "status": "qualification_unknown",
                        "record_complete": False,
                        "job_dir": str(job_dir),
                    }
                )
            else:
                if max_new_controls is not None and new_controls >= max_new_controls:
                    return finish("control_batch_limit_reached")
                if shutil.disk_usage(output.anchor).free < MIN_DISK_HEADROOM_BYTES:
                    return finish("insufficient_disk_headroom")
                write_json(attempt_path, attempt, exclusive=True)
                print(
                    f"  {name} {repeat}/{oracle_repeats if name == 'oracle' else 1} {task.task_id}",
                    flush=True,
                )
                new_controls += 1
                try:
                    record = await run_official_trial(
                        snapshot.tasks_path / task.task_id,
                        output / "jobs",
                        job_name,
                        AgentConfig(name=name),
                        environment,
                        configuration=name,
                        repeat=repeat,
                        endpoint="local",
                    )
                except Exception as exc:
                    record = {
                        "task_id": task.task_id,
                        "configuration": name,
                        "repeat": repeat,
                        "status": "qualification_error",
                        "record_complete": False,
                        "verified": False,
                        "success": None,
                        "original_reward": None,
                        "job_dir": str(job_dir),
                        "error_type": type(exc).__name__,
                    }
            if record.get("job_dir") != str(job_dir):
                record = {
                    "task_id": task.task_id,
                    "configuration": name,
                    "repeat": repeat,
                    "status": "qualification_unknown",
                    "record_complete": False,
                    "job_dir": str(job_dir),
                    "error_type": "JobIdentityMismatch",
                }
            write_json(
                path,
                {"task_identity": identity, "control": attempt, "record": record},
                exclusive=True,
            )
        if name == "oracle":
            oracle.append(record)
        else:
            nop = record
        if not grade_qualification(task, oracle, nop, oracle_repeats)["continuation_allowed"]:
            return finish("qualification_execution_unconfirmed")
    return finish()


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
        "passed": complete
        and len(selected_receipts) == len(tasks)
        and all(row["complete"] and row["passed"] for row in selected_receipts),
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
                if row["complete"] and not row["passed"]
            ],
            "incomplete": [row["task_id"] for row in receipts.values() if not row["complete"]],
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
    max_new_controls: int | None = None,
) -> dict[str, Any]:
    """固定原选择规则与资格次数，失败只改变资格池，不改变评分。"""
    if type(oracle_repeats) is not int or oracle_repeats != 3:
        raise ValueError("本轮预注册固定三次 oracle")
    if max_new_controls is not None and (
        type(max_new_controls) is not int or max_new_controls <= 0
    ):
        raise ValueError("分批控制次数必须是正整数")
    initial = read_json(selection_path)
    selected_tasks = [*initial.get("dev", []), *initial.get("holdout", [])]
    if not initial.get("dev") or not initial.get("holdout"):
        raise ValueError("需要非空开发与最终候选集合")
    sources = {(task["benchmark"], task["revision"]) for task in selected_tasks}
    if len(sources) != 1:
        raise ValueError("一次资格批次只能使用一个固定基准")
    if type(max_candidates) is not int or not len(selected_tasks) <= max_candidates <= 64:
        raise ValueError("资格候选预算不能小于目标任务总数或超过固定上限 64")
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
        "batching_policy": "per-invocation control cap; fixed identities and three-plus-one are unchanged",
    }
    if output.exists():
        if not (output / "plan.json").is_file() or read_json(output / "plan.json") != plan:
            raise ValueError("已有目录不是完全相同的资格计划，拒绝覆盖")
    else:
        output.mkdir(parents=True)
        write_json(output / "plan.json", plan, exclusive=True)
        with (output / "initial-selection.json").open("xb") as stream:
            stream.write(selection_path.read_bytes())
    environment = EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={"messages_upstream": "http://127.0.0.1:9/v1/messages"},
    )
    receipts = {}
    for path in sorted((output / "qualifications").glob("*/qualification.json")):
        row = read_json(path)
        task = indexed.get(row.get("task_id"))
        if task is None or row.get("task_identity") != digest(task.public_dict()):
            raise ValueError("恢复资格记录的任务身份不一致")
        restored = await qualify_one(
            task, snapshot, output, oracle_repeats, environment, max_new_controls=0
        )
        restored.pop("new_controls_executed")
        receipts[task.task_id] = restored
    versions = sorted((output / "selections").glob("selection-*.json"))
    current = read_json(versions[-1]) if versions else proposal
    if not versions:
        write_json(output / "selections" / "selection-000.json", current, exclusive=True)
        versions = [output / "selections" / "selection-000.json"]
    new_controls = 0
    if any(row.get("continuation_allowed") is not True for row in receipts.values()):
        return save_outcome(
            output,
            initial,
            current,
            receipts,
            complete=False,
            reason="qualification_execution_unconfirmed",
        )
    while True:
        tasks = [*current["dev"], *current["holdout"]]
        for task_data in tasks:
            task_id = task_data["task_id"]
            if task_id in receipts and receipts[task_id]["complete"]:
                continue
            if task_id not in receipts and len(receipts) >= max_candidates:
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
            receipt = await qualify_one(
                indexed[task_id],
                snapshot,
                output,
                oracle_repeats,
                environment,
                max_new_controls=None
                if max_new_controls is None
                else max_new_controls - new_controls,
            )
            new_controls += receipt.pop("new_controls_executed")
            receipts[task_id] = receipt
            if not receipt["complete"]:
                return save_outcome(
                    output,
                    initial,
                    current,
                    receipts,
                    complete=False,
                    reason=receipt["stop_reason"] or "qualification_execution_unconfirmed",
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
        rejected = {
            row["leakage_group"]
            for row in receipts.values()
            if row["complete"] and not row["passed"]
        }
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
    parser.add_argument("--max-new-controls", type=int)
    args = parser.parse_args()
    result = asyncio.run(
        qualify(
            args.selection,
            args.cache,
            args.output,
            oracle_repeats=args.oracle_repeats,
            max_candidates=args.max_candidates,
            max_new_controls=args.max_new_controls,
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
