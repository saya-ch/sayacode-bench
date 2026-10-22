"""冻结有限试验顺序、执行单片并严格归并；Agent 与评分仍由原链路承担。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import platform
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from harbor.models.trial.result import TrialResult

from . import study
from .analysis import analyze_experiment
from .artifacts import (
    check_budget,
    file_sha256,
    implementation_identity,
    read_json,
    write_json,
)
from .budget import budget_reason, estimate_paid_usage
from .connections import CANONICAL_MODEL
from .execution import normalize_trial_result, paired_order
from .resources import runtime_record_issues

_FORMAL = {"dev", "holdout", "validation"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RUNNER_SCOPE = {"platform": True, "architecture": True, "host_cohort": "not_implemented"}
_TIME_POLICY = {
    "startup_reserve_seconds": 1200,
    "finalize_reserve_seconds": 900,
    "job_timeout_seconds": 21600,
}
_REFERENCES = (
    "raw_job_result",
    "raw_trial_result",
    "worker_result",
    "runtime",
    "network_isolation",
    "patch",
    "replay_raw_trial_result",
    "replay_runtime",
    "replay_network_isolation",
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve(strict=True)), "sha256": file_sha256(path)}


def _file(reference: Any, bundle: Path | None = None) -> Path:
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not isinstance(reference.get("sha256"), str)
        or not _SHA.fullmatch(reference["sha256"])
    ):
        raise ValueError("工件来源缺少有效路径与 SHA256")
    path = Path(reference["path"]).resolve(strict=True)
    if bundle is not None and not path.is_relative_to(bundle):
        raise ValueError("工件越过固定 bundle；请按原路径恢复")
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise ValueError("原始工件 SHA256 不一致")
    return path


def _rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("记录必须为 JSON 对象")
    return rows


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _key(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return row.get("task_id"), row.get("configuration"), row.get("repeat")


def _schedule(manifest: dict[str, Any], digest: str) -> list[dict[str, Any]]:
    endpoints = manifest.get("connections", ["local"])
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError("计划缺少固定连接")
    reserves: dict[str, int | None] = {}
    for task in manifest["tasks"]:
        values = [
            task.get(section, {}).get(field)
            for section, field in (
                ("environment", "build_timeout_sec"),
                ("agent", "timeout_sec"),
                ("verifier", "timeout_sec"),
            )
        ]
        if any(
            type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            for value in values
        ):
            if manifest["phase"] in _FORMAL:
                raise ValueError("正式任务缺少有限的官方墙钟预算")
            reserves[task["task_id"]] = None
            continue
        reserve = math.ceil(2 * sum(values) + 1200 + 900)
        if reserve > 21600:
            raise ValueError("官方最坏预算超过六小时，不得降低任务预算或缩小原分母")
        reserves[task["task_id"]] = reserve
    return [
        {
            **row,
            "endpoint": endpoints[(row["repeat"] - 1) % len(endpoints)],
            "trial_key": _hash([digest, *_key(row)]),
            "block_id": _hash([digest, row["task_id"], row["repeat"]]),
            "shard_id": f"{manifest['phase']}-{row['sequence']:04d}-{_hash([digest, *_key(row)])[:12]}",
            "reserve_seconds": reserves[row["task_id"]],
        }
        for row in paired_order(manifest)
    ]


def freeze_execution_plan(
    manifest_path: Path,
    runner_policy_path: Path,
    authorization_path: Path,
    output_path: Path,
    *,
    bundle_root: Path | None = None,
    paid_record_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    """用户授权文件是预算与执行范围声明，不是独立认证或凭据。"""
    if output_path.exists():
        raise FileExistsError("分片计划不可覆盖")
    master = read_json(manifest_path)
    if master.get("frozen") is not True or master.get("canonical_model") != CANONICAL_MODEL:
        raise ValueError("需要已冻结的统一模型 master")
    if master.get("phase") not in {*_FORMAL, "calibration"}:
        raise ValueError("不支持的研究阶段")
    if set(analyze_experiment(master, [])["validity_issues"]) - {"missing_trials"}:
        raise ValueError("master 结构或研究规则无效")
    formal = master["phase"] in _FORMAL
    if formal and (
        bundle_root is None
        or not master.get("preflight_passed")
        or master.get("implementation") != implementation_identity()
        or master.get("runtime_evidence_required") is not True
        or set(master.get("qualified_runtime_identities", {}))
        != {task["task_id"] for task in master["tasks"]}
    ):
        raise ValueError("正式分片必须绑定 bundle、前置门禁和当前实现")
    bundle = bundle_root.resolve() if bundle_root is not None else None
    inputs = [manifest_path, runner_policy_path, authorization_path, *paid_record_paths]
    if bundle is not None and any(
        not path.resolve().is_relative_to(bundle) for path in [*inputs, output_path]
    ):
        raise ValueError("冻结输入与计划必须位于固定 bundle")
    runner = read_json(runner_policy_path)
    if runner.get("platform") != "linux" or runner.get("architecture") != "amd64":
        raise ValueError("正式 runner 政策必须固定 Linux/amd64")
    authorization = read_json(authorization_path)
    master_ref = _ref(manifest_path)
    if (
        authorization.get("authorized") is not True
        or authorization.get("phase") != master["phase"]
        or authorization.get("master_manifest_sha256") != master_ref["sha256"]
    ):
        raise ValueError("用户声明未授权这份 master 和阶段")
    artifacts = master.get("artifacts")
    if (
        not isinstance(artifacts, dict)
        or set(artifacts) != {"product_wheel", "requirements", "variants"}
        or set(artifacts["variants"]) != set(master["configurations"])
    ):
        raise ValueError("master 必须冻结生产工件与全部配置")
    digests = [
        artifacts["product_wheel"],
        artifacts["requirements"],
        *artifacts["variants"].values(),
    ]
    if any(not isinstance(value, str) or not _SHA.fullmatch(value) for value in digests):
        raise ValueError("生产工件身份无效")
    paid_refs = [_ref(path) for path in paid_record_paths]
    extra_paid = [row for path in paid_record_paths for row in _rows(path)]
    if extra_paid and master.get("paid_budget") is None:
        raise ValueError("增量费用必须已有冻结金融政策")
    study._continuation_rows(tuple(extra_paid))
    study._paid_inputs(master)
    schedule = _schedule(master, master_ref["sha256"])
    plan = {
        "schema_version": 1,
        "master": master_ref,
        "runner_policy": _ref(runner_policy_path),
        "authorization": _ref(authorization_path),
        "bundle_root": str(bundle) if bundle else None,
        "implementation": implementation_identity(),
        "artifacts": artifacts,
        "schedule": schedule,
        "schedule_sha256": _hash(schedule),
        "financial_policy_sha256": _hash(master.get("paid_budget")),
        "initial_paid_records": paid_refs,
        "runner_policy_enforcement": _RUNNER_SCOPE,
        "time_policy": _TIME_POLICY,
    }
    write_json(output_path, plan, exclusive=True)
    return plan


def _load_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any], Path | None]:
    plan = read_json(path)
    if plan.get("schema_version") != 1:
        raise ValueError("不支持的分片计划版本")
    if plan.get("runner_policy_enforcement") != _RUNNER_SCOPE:
        raise ValueError("不支持的 runner 政策执行范围；宿主 cohort 尚未实现")
    if plan.get("time_policy") != _TIME_POLICY:
        raise ValueError("分片时限政策已漂移")
    bundle = Path(plan["bundle_root"]).resolve() if plan.get("bundle_root") else None
    master = read_json(_file(plan["master"], bundle))
    runner = read_json(_file(plan["runner_policy"], bundle))
    authorization = read_json(_file(plan["authorization"], bundle))
    if (
        master.get("frozen") is not True
        or master.get("canonical_model") != CANONICAL_MODEL
        or plan.get("implementation") != implementation_identity()
        or master.get("artifacts") != plan.get("artifacts")
        or _hash(master.get("paid_budget")) != plan.get("financial_policy_sha256")
    ):
        raise ValueError("master、实现或金融政策已漂移")
    if master["phase"] in _FORMAL and (
        bundle is None or master.get("implementation") != plan["implementation"]
    ):
        raise ValueError("正式实现或 bundle 未绑定")
    if (
        runner.get("platform") != "linux"
        or runner.get("architecture") != "amd64"
        or authorization.get("authorized") is not True
        or authorization.get("phase") != master["phase"]
        or authorization.get("master_manifest_sha256") != plan["master"]["sha256"]
    ):
        raise ValueError("runner 或阶段授权不一致")
    expected = _schedule(master, plan["master"]["sha256"])
    if expected != plan.get("schedule") or _hash(expected) != plan.get("schedule_sha256"):
        raise ValueError("全局顺序被修改")
    for reference in plan.get("initial_paid_records", []):
        _file(reference, bundle)
    return plan, master, bundle


def _native(reference: Any, bundle: Path | None) -> tuple[TrialResult, Path]:
    path = _file(reference, bundle)
    return TrialResult.model_validate(read_json(path)), path.parent


def _record_evidence(
    row: dict[str, Any], master: dict[str, Any], bundle: Path | None
) -> list[dict[str, str]]:
    """重读官方模型与原规范化函数，只复核事实，不重新运行测试或自写评分。"""
    references = [
        row[field]
        for field in _REFERENCES
        if isinstance(row.get(field), dict) and row[field].get("sha256") is not None
    ]
    files = [_ref(_file(reference, bundle)) for reference in references]
    trial, directory = _native(row.get("raw_trial_result"), bundle)
    if trial.config.agent.import_path != "sayacode_bench.adapter:SayacodeAgent":
        raise ValueError("source 不是冻结生产 Agent 的原生配置")
    source_job = Path(str(row.get("source_job", row.get("job_dir", "")))).resolve()
    if directory.parent != source_job:
        raise ValueError("source job 与原生结果目录不一致")
    for argument, digest in (
        ("product_wheel", master["artifacts"]["product_wheel"]),
        ("requirements_path", master["artifacts"]["requirements"]),
        ("variant_path", master["artifacts"]["variants"][row["configuration"]]),
    ):
        files.append(
            _ref(_file({"path": trial.config.agent.kwargs.get(argument), "sha256": digest}, bundle))
        )
    native = normalize_trial_result(
        trial,
        directory,
        configuration=row["configuration"],
        repeat=row["repeat"],
        endpoint=row["endpoint"],
        canonical_model=master["canonical_model"],
        require_replay=master["benchmark"] == "swe-bench-pro-v2",
    )
    for field in (
        "task_id",
        "original_reward",
        "input_tokens",
        "output_tokens",
        "usage",
        "usage_complete",
        "runtime_identity",
        "terminal_http_statuses",
        "failure_category",
    ):
        if native.get(field) != row.get(field):
            raise ValueError(f"source 原生证据与记录冲突：{field}")
    if row.get("status") != "patch_apply_failed" and native["status"] != row.get("status"):
        raise ValueError("source 执行状态冲突")
    if row.get("verified") is True and master["benchmark"] == "swe-bench-pro-v2":
        target, target_directory = _native(row.get("replay_raw_trial_result"), bundle)
        if target.config.agent.import_path != "patch_replay:PatchReplayAgent":
            raise ValueError("重判不是官方 PatchReplayAgent")
        replay = normalize_trial_result(
            target,
            target_directory,
            configuration=row["configuration"],
            repeat=row["repeat"],
            endpoint=row["endpoint"],
            canonical_model=master["canonical_model"],
        )
        if (
            target_directory == directory
            or Path(str(target.config.agent.kwargs.get("source_job", ""))).resolve() != source_job
        ):
            raise ValueError("pristine 重判关联了其他 source")
        patch = _file(row.get("patch"), bundle)
        details_path = target_directory / "agent/replay.json"
        details = read_json(details_path)
        files.append(_ref(details_path))
        applied = (
            type(details.get("apply_rc")) is int
            and details["apply_rc"] == 0
            and details.get("patch") == str(patch)
        ) or (patch.stat().st_size == 0 and details.get("patch") is None)
        expected_success = native["status"] == "completed" and replay["success"] is True
        if (
            not applied
            or replay["verified"] is not True
            or replay["original_reward"] != row.get("replay_reward")
            or replay["runtime_identity"] != row.get("replay_runtime_identity")
            or expected_success != row.get("success")
        ):
            raise ValueError("pristine 原生评分、应用或结果冲突")
    elif row.get("success") is True and native.get("verified") is not True:
        raise ValueError("没有已确认的原生成功证据")
    return files


def _initial_paid(plan: dict[str, Any], bundle: Path | None) -> list[dict[str, Any]]:
    return [
        row for reference in plan["initial_paid_records"] for row in _rows(_file(reference, bundle))
    ]


def _read_receipt(
    path: Path,
    plan_path: Path,
    plan: dict[str, Any],
    master: dict[str, Any],
    bundle: Path | None,
    memo: dict[str, tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    memo = memo if memo is not None else {}
    digest = file_sha256(path)
    if digest in memo:
        return memo[digest]
    receipt = read_json(path)
    if (
        receipt.get("schema_version") != 1
        or type(receipt.get("complete")) is not bool
        or type(receipt.get("continuation_allowed")) is not bool
        or receipt.get("status") not in {"completed", "incomplete", "stopped"}
    ):
        raise ValueError("收据结构或状态无效")
    sequence = receipt.get("sequence")
    if (
        receipt.get("plan_sha256") != file_sha256(plan_path)
        or type(sequence) is not int
        or not 1 <= sequence <= len(plan["schedule"])
    ):
        raise ValueError("receipt 不属于此计划")
    entry = plan["schedule"][sequence - 1]
    if any(receipt.get(key) != entry[key] for key in ("shard_id", "trial_key", "block_id")):
        raise ValueError("receipt 的全局试验身份冲突")
    ledger = read_json(_file(receipt.get("ledger_after"), bundle))
    if ledger.get("plan_sha256") != file_sha256(plan_path):
        raise ValueError("费用账本属于其他计划")
    previous = receipt.get("previous_receipt")
    prefix: list[dict[str, Any]] = []
    if previous is not None:
        previous_path = _file(previous, bundle)
        if previous_path.resolve() == path.resolve():
            raise ValueError("receipt 前序循环")
        parent, state = _read_receipt(previous_path, plan_path, plan, master, bundle, memo)
        if (
            parent["sequence"] != sequence - 1
            or parent.get("complete") is not True
            or parent.get("continuation_allowed") is not True
        ):
            raise ValueError("前序不是连续完整片")
        prefix = state["phase_records"]
        if receipt.get("ledger_before_sha256") != parent["ledger_after"]["sha256"]:
            raise ValueError("账本前序分叉")
    elif sequence != 1 or receipt.get("ledger_before_sha256") is not None:
        raise ValueError("首片或账本前序缺失")
    rows = ledger.get("phase_records")
    if not isinstance(rows, list) or rows[: len(prefix)] != prefix:
        raise ValueError("阶段前缀被覆盖")
    expected_length = sequence if receipt.get("complete") is True else len(prefix)
    if len(rows) not in {expected_length, sequence} or (
        receipt.get("complete") and len(rows) != sequence
    ):
        raise ValueError("账本前缀长度不一致")
    if ledger.get("paid_records") != _initial_paid(plan, bundle):
        raise ValueError("跨阶段费用事实被替换")
    for record, planned in zip(rows, plan["schedule"], strict=False):
        if _key(record) != _key(planned) or record.get("endpoint") != planned["endpoint"]:
            raise ValueError("记录顺序、repeat 或连接不一致")
        _record_evidence(record, master, bundle)
    for reference in receipt.get("evidence_files", []):
        _file(reference, bundle)
    for reference in receipt.get("markers", []):
        _file(reference, bundle)
    if receipt.get("complete") is True:
        if (
            receipt.get("status") != "completed"
            or receipt.get("markers")
            or receipt.get("error_type")
            or receipt.get("validity_issues")
            or any(row.get("record_complete") is not True for row in rows)
            or not estimate_paid_usage(
                rows, paid_endpoints=tuple(sorted({row["endpoint"] for row in rows}))
            )["usage_complete"]
        ):
            raise ValueError("收据的完成旗标没有完整事实支持")
        for row in rows:
            task = next(task for task in master["tasks"] if task["task_id"] == row["task_id"])
            if runtime_record_issues(
                row,
                task,
                master.get("qualified_runtime_identities", {}).get(row["task_id"]),
                replay=master["benchmark"] == "swe-bench-pro-v2",
            ):
                raise ValueError("收据资源事实未确认")
        if receipt.get("continuation_allowed") != (
            _stop_reason(master, rows, ledger["paid_records"]) is None
        ):
            raise ValueError("收据放行旗标与累计止损事实冲突")
    elif receipt.get("continuation_allowed") is not False:
        raise ValueError("未完整片不能继续派发")
    for marker in (
        path.parent / "run/abort.json",
        path.parent / "run/invalid.json",
        path.parent / "execution-error.json",
    ):
        if marker.exists() and receipt.get("complete") is True:
            raise ValueError("已中止片不能通过修改旗标恢复")
    memo[digest] = receipt, ledger
    return receipt, ledger


def _stop_reason(
    master: dict[str, Any], rows: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> str | None:
    reason = check_budget(rows, reported_token_limit=master["reported_token_limit"])
    if reason:
        return reason
    policy, initial = study._paid_inputs(master)
    if policy is not None:
        return budget_reason(
            rows,
            [*initial, *extra],
            limit_cny=policy["limit_cny"],
            stop_fraction=policy["stop_fraction"],
            paid_endpoints=tuple(policy["paid_endpoints"]),
            input_cny_per_million=policy["input_cny_per_million"],
            output_cny_per_million=policy["output_cny_per_million"],
        )
    return None


async def run_shard(
    plan_path: Path,
    shard_id: str,
    previous_receipt_path: Path | None,
    *,
    output: Path,
    cache: Path,
    wheel: Path,
    requirements: Path,
    variants: dict[str, Path],
    connections: dict[str, Path],
    private_home: Path,
    deadline_epoch: float | None = None,
) -> dict[str, Any]:
    """完成或未完成的片均保存 receipt；已存在的尝试从不自动重放。"""
    plan, master, bundle = _load_plan(plan_path)
    if deadline_epoch is not None and (
        type(deadline_epoch) not in {int, float} or not math.isfinite(deadline_epoch)
    ):
        raise ValueError("截止时间必须是有限 epoch 数值")
    entry = next((row for row in plan["schedule"] if row["shard_id"] == shard_id), None)
    if entry is None:
        raise ValueError("分片不在冻结计划中")
    if bundle is not None:
        if (
            platform.system().lower() != "linux"
            or platform.machine().lower() not in {"amd64", "x86_64"}
            or output.resolve() != bundle / "shards" / shard_id
            or cache.resolve() != bundle / "cache"
            or private_home.resolve().is_relative_to(bundle)
            or any(
                not path.resolve().is_relative_to(bundle / "inputs")
                for path in [wheel, requirements, *variants.values()]
            )
        ):
            raise ValueError("执行绑定不符合固定 Linux bundle")
    expected_artifacts = {
        "product_wheel": file_sha256(wheel),
        "requirements": file_sha256(requirements),
        "variants": {label: file_sha256(path) for label, path in variants.items()},
    }
    if expected_artifacts != plan["artifacts"]:
        raise ValueError("实际生产工件与冻结计划不一致")
    profile_metadata = {
        label: {key: value for key, value in read_json(path).items() if key != "api_key"}
        for label, path in connections.items()
    }
    if profile_metadata != master.get("connection_profiles"):
        raise ValueError("私有连接的非秘密参数已漂移")
    binding = {
        "cache": str(cache.resolve()),
        "private_home": str(private_home.resolve()),
        "profiles": profile_metadata,
        "artifacts": expected_artifacts,
    }
    previous_ref = _ref(previous_receipt_path) if previous_receipt_path else None
    receipt_path = output / "shard-receipt.json"
    if receipt_path.is_file():
        existing, _ = _read_receipt(receipt_path, plan_path, plan, master, bundle)
        if existing.get("binding") != binding or existing.get("previous_receipt") != previous_ref:
            raise ValueError("已有尝试的输入或前序已改变")
        return existing
    if output.exists():
        raise ValueError("已有未收尾片，必须保留现场，不得自动重跑")
    prefix: list[dict[str, Any]] = []
    before_hash = None
    if previous_receipt_path is not None:
        previous, before = _read_receipt(previous_receipt_path, plan_path, plan, master, bundle)
        if (
            previous.get("continuation_allowed") is not True
            or previous["sequence"] != entry["sequence"] - 1
        ):
            raise ValueError("前序不允许继续，或并非下一片")
        prefix, before_hash = before["phase_records"], previous["ledger_after"]["sha256"]
    elif entry["sequence"] != 1:
        raise ValueError("非首片缺少严格前序 receipt")
    extra = _initial_paid(plan, bundle)
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "attempt.json",
        {
            "plan_sha256": file_sha256(plan_path),
            **entry,
            "binding": binding,
            "previous_receipt": previous_ref,
        },
        exclusive=True,
    )
    reason = _stop_reason(master, prefix, extra)
    if (
        reason is None
        and deadline_epoch is not None
        and (
            entry["reserve_seconds"] is None
            or deadline_epoch - time.time() < entry["reserve_seconds"]
        )
    ):
        reason = "insufficient_job_time"
    error_type = None
    if reason is None:
        try:
            execution = study.run_phase(
                _file(plan["master"], bundle),
                output / "run",
                cache,
                wheel,
                requirements,
                variants,
                connections,
                private_home,
                continuation=study.PhaseContinuation(
                    sequences=(entry["sequence"],),
                    phase_records=tuple(prefix),
                    paid_records=tuple(extra),
                ),
            )
            if deadline_epoch is None:
                await execution
            else:
                await asyncio.wait_for(
                    execution, timeout=max(0.001, deadline_epoch - time.time() - 900)
                )
        except Exception as exc:
            error_type = type(exc).__name__
            write_json(output / "execution-error.json", {"error_type": error_type}, exclusive=True)
    record_path = output / "run/records.jsonl"
    rows = _rows(record_path) if record_path.is_file() else prefix
    evidence: list[dict[str, str]] = []
    issues = []
    complete = len(rows) == entry["sequence"] and rows[: len(prefix)] == prefix
    try:
        for row, planned in zip(rows, plan["schedule"], strict=False):
            if _key(row) != _key(planned) or row.get("endpoint") != planned["endpoint"]:
                raise ValueError("原生记录偏离全局顺序")
            evidence.extend(_record_evidence(row, master, bundle))
            complete = complete and row.get("record_complete") is True
            task = next(task for task in master["tasks"] if task["task_id"] == row["task_id"])
            issues.extend(
                runtime_record_issues(
                    row,
                    task,
                    master.get("qualified_runtime_identities", {}).get(row["task_id"]),
                    replay=master["benchmark"] == "swe-bench-pro-v2",
                )
            )
    except (ValueError, KeyError, OSError) as exc:
        issues.append(f"native_evidence_invalid:{type(exc).__name__}")
        complete = False
    if error_type or (output / "run/abort.json").exists():
        issues.append("execution_aborted")
    try:
        if (
            rows
            and not estimate_paid_usage(
                rows, paid_endpoints=tuple(sorted({row["endpoint"] for row in rows}))
            )["usage_complete"]
        ):
            issues.append("usage_unconfirmed")
    except (ValueError, KeyError, TypeError):
        issues.append("usage_identity_invalid")
    complete = complete and not issues
    try:
        after_reason = _stop_reason(master, rows, extra)
    except (ValueError, KeyError, TypeError):
        after_reason = "accounting_unconfirmed"
        issues.append("accounting_unconfirmed")
        complete = False
    ledger_path = output / "ledger.json"
    write_json(
        ledger_path,
        {
            "schema_version": 1,
            "plan_sha256": file_sha256(plan_path),
            "phase_records": rows,
            "paid_records": extra,
            "unresolved_execution": not complete and reason is None,
        },
        exclusive=True,
    )
    receipt = {
        "schema_version": 1,
        "plan_sha256": file_sha256(plan_path),
        **{key: entry[key] for key in ("shard_id", "sequence", "trial_key", "block_id")},
        "status": "completed" if complete else "stopped" if reason else "incomplete",
        "complete": bool(complete),
        "continuation_allowed": bool(complete and not issues and not after_reason),
        "stop_reason": reason or after_reason,
        "error_type": error_type,
        "validity_issues": sorted(set(issues)),
        "previous_receipt": previous_ref,
        "ledger_before_sha256": before_hash,
        "ledger_after": _ref(ledger_path),
        "binding": binding,
        "evidence_files": evidence,
        "runner_policy_enforcement": _RUNNER_SCOPE,
        "markers": [
            _ref(path)
            for path in (
                output / "run/abort.json",
                output / "run/invalid.json",
                output / "execution-error.json",
            )
            if path.is_file()
        ],
    }
    write_json(receipt_path, receipt, exclusive=True)
    return receipt


def merge_shards(plan_path: Path, receipt_paths: Sequence[Path], output: Path) -> dict[str, Any]:
    """幂等接收相同 receipt；全 master 分母始终交给原分析函数。"""
    plan, master, bundle = _load_plan(plan_path)
    if output.exists():
        raise FileExistsError("归并使用新目录，保留旧派生结果")
    accepted: dict[int, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    memo: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for path in receipt_paths:
        receipt, ledger = _read_receipt(path, plan_path, plan, master, bundle, memo)
        sequence, digest = receipt["sequence"], file_sha256(path)
        if sequence in accepted and accepted[sequence][0] != digest:
            raise ValueError("同一全局试验存在冲突 receipt")
        accepted[sequence] = digest, receipt, ledger
    for digest, (receipt, ledger) in memo.items():
        sequence = receipt["sequence"]
        if sequence in accepted and accepted[sequence][0] != digest:
            raise ValueError("前序链存在冲突 receipt")
        accepted[sequence] = digest, receipt, ledger
    rows: list[dict[str, Any]] = []
    sources: dict[str, tuple[Any, Any, Any]] = {}
    issues = []
    for sequence in sorted(accepted):
        _, receipt, ledger = accepted[sequence]
        if ledger["phase_records"][: len(rows)] != rows:
            raise ValueError("片间阶段前缀冲突")
        rows = ledger["phase_records"]
        issues.extend(receipt.get("validity_issues", []))
        if not receipt.get("complete"):
            issues.append(f"incomplete_shard:{receipt['shard_id']}")
    for row in rows:
        for field in ("request_sha256", "source_job", "job_dir"):
            identity = row.get(field)
            if isinstance(identity, str):
                alias = (
                    f"request:{identity}"
                    if field == "request_sha256"
                    else f"job:{Path(identity).resolve()}"
                )
                if alias in sources and sources[alias] != _key(row):
                    raise ValueError("同一次 source 被复用为多个试验")
                sources[alias] = _key(row)
    missing = [row for row in plan["schedule"] if _key(row) not in {_key(item) for item in rows}]
    merged_manifest = {
        **master,
        "validity_issues": sorted(set([*master.get("validity_issues", []), *issues])),
    }
    _, initial = study._paid_inputs(master)
    extra = _initial_paid(plan, bundle)
    summary = study.phase_summary(merged_manifest, rows, prior_records=[*initial, *extra])
    output.mkdir(parents=True, exist_ok=False)
    _write_rows(output / "records.jsonl", rows)
    _write_rows(output / "accounting-records.jsonl", [*initial, *extra, *rows])
    write_json(output / "summary.json", summary)
    write_json(output / "missing.json", missing)
    write_json(
        output / "manifest.json",
        {
            **merged_manifest,
            "sharded_master_sha256": plan["master"]["sha256"],
        },
    )
    if issues:
        write_json(
            output / "invalid.json",
            {
                "reason": "shard_evidence_invalid",
                "plan_sha256": file_sha256(plan_path),
                "validity_issues": sorted(set(issues)),
            },
        )
    complete = (
        not missing
        and len(rows) == len(plan["schedule"])
        and all(
            accepted.get(index, (None, {}, None))[1].get("complete") is True
            for index in range(1, len(plan["schedule"]) + 1)
        )
    )
    result = {
        "schema_version": 1,
        "plan_sha256": file_sha256(plan_path),
        "complete": bool(complete),
        "accepted_receipts": len(accepted),
        "records": _ref(output / "records.jsonl"),
        "summary": summary,
        "missing_trials": len(missing),
        "validity_issues": merged_manifest["validity_issues"],
    }
    write_json(output / "merge-receipt.json", result, exclusive=True)
    return result
