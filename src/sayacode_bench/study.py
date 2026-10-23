"""按冻结清单执行研究阶段，所有任务执行和判分交给 Harbor。"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from harbor.models.trial.config import AgentConfig, EnvironmentConfig

from .analysis import analyze_experiment
from .artifacts import (
    check_budget,
    fatal_stop_reason,
    file_sha256,
    implementation_identity,
    read_json,
    record_stop,
    report_manifest,
    write_json,
)
from .budget import budget_reason, estimate_paid_usage
from .connections import CANONICAL_MODEL, messages_endpoint, read_connection
from .execution import paired_order, remaining_order, replay_official_trial, run_official_trial
from .gates import validate_directories
from .locking import validate_candidate_receipt
from .resources import resource_status, runtime_record_issues
from .settlement import historical_settlement as read_historical_settlement
from .sources import SOURCES, fetch_source, sha256_file


@dataclass(frozen=True)
class PhaseContinuation:
    """已由分片层核验的阶段前缀与追加费用；不替换 master 的冻结输入。"""

    sequences: tuple[int, ...]
    phase_records: tuple[dict[str, Any], ...] = ()
    paid_records: tuple[dict[str, Any], ...] = ()


def _continuation_rows(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    if not isinstance(rows, tuple) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("延续记录必须是对象 tuple")
    copied = deepcopy(list(rows))
    if any(row.get("record_complete") is not True for row in copied):
        raise ValueError("延续历史包含未收尾试验，不能继续")
    if copied:
        names = {row.get("endpoint") for row in copied}
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("延续历史必须保留真实连接别名")
        aliases = tuple(sorted(str(name) for name in names))
        # 这里只复用用量覆盖与身份冲突检查；实际费用仍按 master 的付费连接计算。
        if not estimate_paid_usage(copied, paid_endpoints=aliases)["usage_complete"]:
            raise ValueError("延续历史存在未知用量，不能继续")
    return copied


def _phase_prefix(
    manifest: dict[str, Any], schedule: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    if len(rows) > len(schedule):
        raise ValueError("阶段历史超过原计划")
    connections = manifest.get("connections", ["local"])
    if not isinstance(connections, list) or not connections:
        raise ValueError("延续必须保留 master 的非空连接顺序")
    for item, row in zip(schedule, rows):
        if any(row.get(key) != item[key] for key in ("task_id", "configuration", "repeat")):
            raise ValueError("阶段历史不是全局 schedule 的严格前缀")
        if row.get("endpoint") != connections[(item["repeat"] - 1) % len(connections)]:
            raise ValueError("阶段历史连接与 master 的 repeat 路由不同")
        for field in ("sequence", "global_sequence"):
            if field in row and (type(row[field]) is not int or row[field] != item["sequence"]):
                raise ValueError("阶段历史的全局序号不一致")
    if fatal_stop_reason(rows):
        raise ValueError("阶段历史已触发外部故障止损，不能继续")
    issues = analyze_experiment(manifest, rows)["validity_issues"]
    if set(issues) - {"missing_trials"}:
        raise ValueError("阶段历史含未知、无效或不可比较的执行事实")


def _continue_phase(
    manifest: dict[str, Any],
    schedule: list[dict[str, Any]],
    local: list[dict[str, Any]],
    continuation: PhaseContinuation,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    history = _continuation_rows(continuation.phase_records)
    paid = _continuation_rows(continuation.paid_records)
    sequences = continuation.sequences
    if (
        not isinstance(sequences, tuple)
        or not sequences
        or any(type(value) is not int for value in sequences)
        or sequences != tuple(range(len(history) + 1, len(history) + len(sequences) + 1))
        or sequences[-1] > len(schedule)
    ):
        raise ValueError("延续只接受阶段前缀之后紧接的全局序号")
    _phase_prefix(manifest, schedule, history)
    _continuation_rows(tuple(local))
    _phase_prefix(manifest, schedule, local)
    if len(local) > len(history) + len(sequences) or any(a != b for a, b in zip(local, history)):
        raise ValueError("本片已有记录与传入阶段历史冲突或超出授权序号")
    records = local if len(local) >= len(history) else history

    def encoded(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    identity = {
        "sequences": list(sequences),
        "phase_records_sha256": encoded(history),
        "paid_records_sha256": encoded(paid),
    }
    return deepcopy(records), paid, identity


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("逐次记录必须是 JSON 对象")
    return rows


def _budget_arguments(policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(policy.get("paid_endpoints"), list):
        raise ValueError("付费连接必须为冻结的别名列表")
    arguments = {
        "paid_endpoints": tuple(policy["paid_endpoints"]),
        "input_cny_per_million": policy["input_cny_per_million"],
        "output_cny_per_million": policy["output_cny_per_million"],
    }
    if policy.get("pricing_method") == "observed_cache_v1":
        arguments.update(
            pricing_method="observed_cache_v1",
            cache_read_cny_per_million=policy["cache_read_cny_per_million"],
        )
    elif policy.get("pricing_method") not in {None, "full_input_peak_v1"}:
        raise ValueError("未知的冻结计价方法")
    if "historical_settlement" in policy:
        arguments["historical_settlement"] = policy["historical_settlement"]
    return arguments


def _checked_reference(reference: Any) -> Path:
    """重开冻结的产品适配证据；不接受仅声明通过的布尔值。"""
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not isinstance(reference.get("sha256"), str)
    ):
        raise ValueError("新研究轮次的证据引用无效")
    path = Path(reference["path"])
    if path.is_symlink() or file_sha256(path) != reference["sha256"]:
        raise ValueError("新研究轮次的原始证据发生变化")
    return path.resolve(strict=True)


def validate_execution_inputs(manifest: dict[str, Any]) -> None:
    """新轮次同时绑定完整安装预检、先导计量及协议；不复用先导成绩。"""
    epoch = manifest.get("execution_epoch")
    policy = manifest.get("paid_budget")
    if epoch is None:
        if isinstance(policy, dict) and "pilot_carry" in policy:
            raise ValueError("先导费用延续必须同时绑定新执行协议和安装预检")
        return
    if not isinstance(epoch, dict) or epoch.get("id") != "restart-v2":
        raise ValueError("未知的新研究轮次")
    expected = Path(__file__).resolve().parents[2] / "studies/execution-protocol-v13.json"
    protocol = _checked_reference(epoch.get("protocol"))
    if protocol.read_bytes() != expected.read_bytes():
        raise ValueError("新执行协议与固定源码不一致")
    contract = read_json(protocol)
    statistics = expected.parent / "sensitivity-protocol-v12.json"
    if file_sha256(statistics) != contract.get("statistical_protocol_sha256"):
        raise ValueError("原 v12 统计协议的字节身份发生变化")
    from scripts.analyze_sensitivity import protocol_identity

    current_analysis = protocol_identity()
    validate_statistical_continuity(read_json(statistics), current_analysis)
    analysis = _checked_reference(epoch.get("analysis_protocol"))
    if read_json(analysis) != current_analysis:
        raise ValueError("新轮次分析身份与实际执行源码不一致")
    if not isinstance(policy, dict) or "pilot_carry" not in policy:
        raise ValueError("新研究轮次缺少先导费用延续证据")
    if policy.get("limit_cny") != 100 or policy.get("stop_fraction") != 0.8:
        raise ValueError("新轮次必须沿用同一百元累计预算和百分之八十停止阈值")
    _validate_pilot_epoch_contract(manifest, policy)
    benchmark, phase = manifest.get("benchmark"), manifest.get("phase")
    task_count = 8 if phase == "dev" else 24 if benchmark == "swe-bench-pro-v2" else 12
    expected_repeats = 2 if benchmark == "swe-bench-pro-v2" else 1
    if (
        benchmark not in {"swe-bench-pro-v2", "terminal-bench-2.1"}
        or phase not in {"dev", "holdout", "validation"}
        or benchmark == "terminal-bench-2.1"
        and phase == "dev"
        or len(manifest.get("tasks", [])) != task_count
        or manifest.get("repeats") != expected_repeats
        or phase == "dev"
        and manifest.get("configurations") != ["baseline", "diagnostic", "focused"]
    ):
        raise ValueError("新轮次必须保留预声明的完整开发和最终阶段规模")
    from .installation import validate_installation_preflight

    installation_ref = epoch.get("installation_preflight")
    _checked_reference(installation_ref)
    assert isinstance(installation_ref, dict)
    validate_installation_preflight(
        installation_ref,
        tasks=manifest.get("tasks"),
        artifacts=manifest.get("artifacts"),
        implementation=manifest.get("implementation"),
    )


def validate_statistical_continuity(original: dict[str, Any], current: dict[str, Any]) -> None:
    """执行实现可在新轮次改变，统计方法及其实际代码必须保留原身份。"""
    methods = (
        "schema_version",
        "script_sha256",
        "analysis_sha256",
        "validity_rules_sha256",
        "budget_sha256",
        "resource_rules_sha256",
        "samples",
        "seed",
        "absolute_unit",
        "cluster_unit",
        "cluster_estimator",
        "role",
    )
    if any(key not in original or original[key] != current.get(key) for key in methods):
        raise ValueError("原 v12 统计、候选或计价方法发生变化")


def _validate_pilot_epoch_contract(manifest: dict[str, Any], policy: dict[str, Any]) -> None:
    """固定先导已由 carry 核原件；金融、连接和原配置只从该唯一来源继承。"""
    from .pilot_carry import validate_pilot_carry

    reference = policy["pilot_carry"]
    carry_path = _checked_reference(reference)
    validate_pilot_carry(reference)
    carry = read_json(carry_path)
    original = read_json(_checked_reference(carry["original_members"]["master"]))
    excluded = {"prior_records", "pilot_carry"}
    financial = {key: value for key, value in policy.items() if key not in excluded}
    if financial != {
        key: value for key, value in original["paid_budget"].items() if key not in excluded
    }:
        raise ValueError("原价格、历史核销、预算起点或金融规则不得在新轮次改变")
    if manifest.get("connection_profiles") != original["connection_profiles"]:
        raise ValueError("新轮次必须保留原模型连接和上下文配置")
    actual, expected = manifest.get("artifacts", {}), original["artifacts"]
    if any(actual.get(key) != expected[key] for key in ("product_wheel", "requirements")) or any(
        expected["variants"].get(key) != value for key, value in actual.get("variants", {}).items()
    ):
        raise ValueError("新轮次必须保留原生产包、依赖和算法配置")


def _check_budget_references(policy: dict[str, Any]) -> None:
    if policy.get("pricing_method") == "observed_cache_v1" and (
        policy.get("pricing_implementation_sha256")
        != file_sha256(Path(__file__).with_name("budget.py"))
        or policy.get("cache_semantics") != "input_includes_cache_read_and_creation_v1"
        or policy.get("cache_evidence_collector") != "langchain_callback_usage_v1"
    ):
        raise ValueError("已冻结的缓存计价实现或语义发生变化")
    references = [policy["price_snapshot"], *policy["prior_records"]]
    for reference in references:
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ValueError("费用证据身份格式无效")
        path = Path(reference["path"]).resolve(strict=True)
        if file_sha256(path) != reference.get("sha256"):
            raise ValueError("已冻结的价格或历史费用记录发生变化")
    if "pilot_carry" in policy:
        from .pilot_carry import validate_pilot_carry

        carry = validate_pilot_carry(policy["pilot_carry"])
        if not carry or any(reference not in policy["prior_records"] for reference in carry):
            raise ValueError("先导已发生的模型费用没有完整延续")
    if "historical_settlement" in policy:
        read_historical_settlement(
            policy["historical_settlement"], paid_endpoints=tuple(policy["paid_endpoints"])
        )
    if policy.get("pricing_method") == "observed_cache_v1":
        snapshot = read_json(Path(policy["price_snapshot"]["path"]))
        if (
            snapshot.get("pricing_method") != "observed_cache_v1"
            or any(
                binding != snapshot.get("connection_requirements")
                for binding in policy.get("connection_bindings", {}).values()
            )
            or policy.get("cache_read_cny_per_million")
            != snapshot["conservative_estimation"].get("cache_read_cny_per_million")
        ):
            raise ValueError("缓存价格或连接绑定与已冻结快照不同")


def _check_pricing_profiles(manifest: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if policy.get("pricing_method") != "observed_cache_v1":
        return
    profiles = manifest.get("connection_profiles")
    bindings = policy.get("connection_bindings")
    if (
        not isinstance(profiles, Mapping)
        or not isinstance(bindings, Mapping)
        or set(bindings) != set(policy["paid_endpoints"])
    ):
        raise ValueError("观测缓存价格缺少真实付费连接绑定")
    for alias, binding in bindings.items():
        profile = profiles.get(alias)
        if (
            not isinstance(profile, Mapping)
            or {
                key: str(profile.get(key, "")).rstrip("/")
                if key == "base_url"
                else profile.get(key)
                for key in ("protocol", "base_url", "model_id")
            }
            != binding
        ):
            raise ValueError("实际连接协议、地址或模型与冻结价格不一致")


def _paid_inputs(manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    validate_execution_inputs(manifest)
    policy = manifest.get("paid_budget")
    if policy is None:
        return None, []
    if not isinstance(policy, dict) or not isinstance(policy.get("prior_records"), list):
        raise ValueError("paid_budget 必须包含冻结的历史记录列表")
    _check_pricing_profiles(manifest, policy)
    _check_budget_references(policy)
    prior = [
        row for reference in policy["prior_records"] for row in _records(Path(reference["path"]))
    ]
    _check_budget_references(policy)
    # 同时校验金额、比例、历史记录身份及完整性；返回停止理由由派发层处理。
    budget_reason(
        [],
        prior,
        limit_cny=policy["limit_cny"],
        stop_fraction=policy["stop_fraction"],
        **_budget_arguments(policy),
    )
    return policy, prior


def freeze_paid_budget(
    *,
    limit_cny: float | None,
    stop_fraction: float = 0.8,
    price_snapshot: Path | None = None,
    prior_records: list[Path] | None = None,
    historical_settlement: Path | None = None,
    paid_endpoints: list[str] | None = None,
    connection_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    pilot_carry: Path | None = None,
) -> dict[str, Any] | None:
    """只冻结显式授权的金额；价格和全部先前阶段记录以路径及内容哈希绑定。"""
    if limit_cny is None:
        if (
            price_snapshot is not None
            or prior_records
            or historical_settlement is not None
            or pilot_carry is not None
            or paid_endpoints
            or stop_fraction != 0.8
        ):
            raise ValueError("费用配置需要显式的 --paid-limit-cny")
        return None
    if price_snapshot is None:
        raise ValueError("付费预算必须声明 --paid-price-snapshot")
    path = price_snapshot.resolve(strict=True)
    snapshot_hash = file_sha256(path)
    snapshot = read_json(path)
    if file_sha256(path) != snapshot_hash:
        raise ValueError("读取期间价格快照发生变化")
    if snapshot.get("currency") != "CNY" or snapshot.get("unit_tokens") != 1_000_000:
        raise ValueError("价格快照必须按人民币／百万 tokens 计价")
    if str(snapshot.get("model_id", "")).split("/")[-1] != CANONICAL_MODEL:
        raise ValueError("价格快照与研究模型不同")
    prices = snapshot["conservative_estimation"]
    observed = snapshot.get("pricing_method") == "observed_cache_v1"
    if snapshot.get("pricing_method") not in {None, "full_input_peak_v1", "observed_cache_v1"}:
        raise ValueError("不支持的价格快照计价方法")
    if not isinstance(prices, dict) or prices.get("cache_discount_applied") is not False:
        raise ValueError("本研究必须使用忽略缓存优惠的固定高档费率")
    tariffs = snapshot.get("rates")
    if not isinstance(tariffs, list) or not tariffs:
        raise ValueError("价格快照缺少已观测的费率分档")
    checked = [
        estimate_paid_usage(
            [], input_cny_per_million=row["input_cache_miss"], output_cny_per_million=row["output"]
        )
        for row in tariffs
    ]
    if prices["input_cny_per_million"] != max(
        row["input_cny_per_million"] for row in checked
    ) or prices["output_cny_per_million"] != max(row["output_cny_per_million"] for row in checked):
        raise ValueError("保守估价必须采用快照中的最高输入和输出单价")
    if observed and (
        prices.get("cache_read_cny_per_million") != max(row["input_cache_hit"] for row in tariffs)
        or snapshot.get("cache_write_price") is not None
        or snapshot.get("cache_semantics") != "input_includes_cache_read_and_creation_v1"
        or snapshot.get("cache_evidence_collector") != "langchain_callback_usage_v1"
        or snapshot.get("pricing_implementation_sha256")
        != file_sha256(Path(__file__).with_name("budget.py"))
    ):
        raise ValueError("观测缓存计价必须冻结最高读取费率、原生语义与当前实现")
    references = []
    for prior in sorted({item.resolve(strict=True) for item in prior_records or []}):
        references.append({"path": str(prior), "sha256": file_sha256(prior)})
    policy = {
        "schema_version": 1,
        "limit_cny": limit_cny,
        "stop_fraction": stop_fraction,
        "paid_endpoints": paid_endpoints or prices.get("paid_endpoints", ["remote"]),
        "input_cny_per_million": prices["input_cny_per_million"],
        "output_cny_per_million": prices["output_cny_per_million"],
        "price_snapshot": {"path": str(path), "sha256": snapshot_hash},
        "prior_records": references,
        "provider_enforced_currency_cap": False,
    }
    if historical_settlement is not None:
        settlement_path = historical_settlement.resolve(strict=True)
        policy["historical_settlement"] = {
            "path": str(settlement_path),
            "sha256": file_sha256(settlement_path),
        }
    if pilot_carry is not None:
        path = pilot_carry.resolve(strict=True)
        policy["pilot_carry"] = {"path": str(path), "sha256": file_sha256(path)}
    if observed:
        requirements = snapshot.get("connection_requirements")
        aliases = policy["paid_endpoints"]
        if (
            not isinstance(requirements, dict)
            or set(requirements) != {"protocol", "base_url", "model_id"}
            or not isinstance(connection_profiles, Mapping)
        ):
            raise ValueError("观测缓存快照必须声明实际协议、地址和模型，且提供连接配置")
        policy.update(
            pricing_method="observed_cache_v1",
            cache_read_cny_per_million=prices["cache_read_cny_per_million"],
            cache_creation_cny_per_million=None,
            cache_semantics=snapshot["cache_semantics"],
            cache_evidence_collector=snapshot["cache_evidence_collector"],
            pricing_implementation_sha256=snapshot["pricing_implementation_sha256"],
            connection_bindings={alias: dict(requirements) for alias in aliases},
        )
    # 冻结金融输入时协议和安装预检由 CLI 一并核验；这里先核全部原财务引用。
    _check_pricing_profiles({"connection_profiles": connection_profiles}, policy)
    _check_budget_references(policy)
    budget_reason(
        [],
        [row for reference in references for row in _records(Path(reference["path"]))],
        limit_cny=policy["limit_cny"],
        stop_fraction=policy["stop_fraction"],
        **_budget_arguments(policy),
    )
    return policy


def paid_budget_report(
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    prior_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """本地汇总保留来源路径与哈希；发布前仍需剥离本机路径，不含私有连接正文。"""
    policy = manifest.get("paid_budget")
    if policy is None:
        return None
    if prior_records is None:
        policy, prior_records = _paid_inputs(manifest)
    assert isinstance(policy, dict) and prior_records is not None
    evidence_valid = True
    try:
        validate_execution_inputs(manifest)
        _check_pricing_profiles(manifest, policy)
        _check_budget_references(policy)
    except (OSError, ValueError):
        evidence_valid = False
    arguments = _budget_arguments(policy)
    return {
        **estimate_paid_usage([*prior_records, *records], **arguments),
        "limit_cny": policy["limit_cny"],
        "stop_fraction": policy["stop_fraction"],
        "stop_threshold_cny": float(
            Decimal(str(policy["limit_cny"])) * Decimal(str(policy["stop_fraction"]))
        ),
        "stop_reason": budget_reason(
            records,
            prior_records,
            limit_cny=policy["limit_cny"],
            stop_fraction=policy["stop_fraction"],
            **arguments,
        ),
        "price_snapshot": policy["price_snapshot"],
        "prior_records": policy["prior_records"],
        "evidence_valid": evidence_valid,
        "provider_enforced_currency_cap": False,
        "boundary": "task dispatch only; in-flight requests, retries and missing usage are not a hard currency cap",
    }


def _paid_stop_reason(
    policy: dict[str, Any] | None,
    records: list[dict[str, Any]],
    prior: list[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
) -> str | None:
    if policy is None:
        return None
    if manifest is not None:
        try:
            validate_execution_inputs(manifest)
        except (OSError, ValueError, KeyError, TypeError):
            return "execution_epoch_evidence_changed"
    try:
        _check_budget_references(policy)
    except (OSError, ValueError):
        return "paid_budget_evidence_changed"
    try:
        return budget_reason(
            records,
            prior,
            limit_cny=policy["limit_cny"],
            stop_fraction=policy["stop_fraction"],
            **_budget_arguments(policy),
        )
    except (ValueError, KeyError, TypeError):
        return "paid_budget_record_invalid"


def phase_summary(
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    prior_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行与只读报告使用同一份结果，费用证据异常不抹去已经保存的任务事实。"""
    summary = analyze_experiment(manifest, records)
    if manifest.get("paid_budget") is not None:
        try:
            budget = paid_budget_report(manifest, records, prior_records=prior_records)
        except (OSError, ValueError, KeyError, TypeError):
            budget = {
                "known_estimate_cny": None,
                "usage_complete": False,
                "total_bill_cny": None,
                "evidence_valid": False,
                "stop_reason": "paid_budget_record_invalid",
                "provider_enforced_currency_cap": False,
            }
        summary["paid_budget"] = budget
        if budget and (
            not budget["evidence_valid"]
            or manifest["paid_budget"].get("pricing_method") == "observed_cache_v1"
            and not budget["usage_complete"]
        ):
            summary["validity_issues"] = sorted(
                set(
                    [
                        *summary["validity_issues"],
                        "paid_budget_evidence_invalid"
                        if not budget["evidence_valid"]
                        else "paid_usage_incomplete",
                    ]
                )
            )
            for field in (
                "formal_comparison_eligible",
                "formal_validation_eligible",
                "final_result_eligible",
            ):
                summary[field] = False
            if isinstance(summary.get("comparison"), dict):
                summary["comparison"]["bootstrap"] = None
    return summary


def _save_records(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _runtime_confirmed(
    record: dict[str, Any],
    *,
    replay: bool,
    qualified: dict[str, Any] | None = None,
    task_environment: dict[str, Any] | None = None,
) -> bool:
    """源、重判都必须符合任务声明，并与冻结资格的实际资源一致。"""
    return not runtime_record_issues(
        record, {"environment": task_environment or {}}, qualified, replay=replay
    )


def _prepare(
    manifest_path: Path,
    output: Path,
    cache: Path,
    wheel: Path,
    requirements: Path,
    variants: dict[str, Path],
) -> tuple[dict[str, Any], Path, Path]:
    output = output.resolve()
    manifest = read_json(manifest_path)
    validate_execution_inputs(manifest)
    if manifest.get("canonical_model") != CANONICAL_MODEL or manifest.get("frozen") is not True:
        raise ValueError("先冻结统一模型和研究清单，再开始真实试验")
    if set(variants) != set(manifest["configurations"]):
        raise ValueError("运行配置与冻结清单不一致")
    if manifest.get("phase") != "calibration":
        expected = manifest.get("artifacts", {})
        actual = {
            "product_wheel": file_sha256(wheel),
            "requirements": file_sha256(requirements),
            "variants": {name: file_sha256(path) for name, path in variants.items()},
        }
        if expected != actual:
            raise ValueError("正式研究的生产包、锁定依赖或候选配置身份不一致")
        if not manifest.get("preflight_passed"):
            raise ValueError("正式研究必须有已通过的环境与评分门禁")
        if manifest.get("implementation") != implementation_identity():
            raise ValueError("正式研究的评测实现身份已变化")
        qualified = manifest.get("qualified_runtime_identities")
        if (
            not isinstance(qualified, dict)
            or set(qualified) != {task["task_id"] for task in manifest["tasks"]}
            or any(
                not isinstance(value, dict)
                or value.get("available") is not True
                or not all(value.get(key) for key in ("image_id", "architecture", "os"))
                for value in qualified.values()
            )
        ):
            raise ValueError("正式研究必须冻结每道任务的资格镜像与平台身份")
        if any(
            resource_status(qualified[task["task_id"]], task.get("environment", {})) is not True
            for task in manifest["tasks"]
        ):
            raise ValueError("正式研究的资格资源、Docker 或 cgroup 限制未确认")
        if manifest.get("runtime_evidence_required") is not True:
            raise ValueError("正式研究必须启用逐次资源核验，不能关闭冻结资格比对")
        if manifest.get("phase") in {"holdout", "validation"}:
            receipt = manifest.get("candidate_receipt")
            if (
                not isinstance(receipt, dict)
                or file_sha256(Path(receipt["path"])) != receipt["sha256"]
            ):
                raise ValueError("最终阶段缺少冻结的开发候选签收")
            validate_candidate_receipt(Path(receipt["path"]), manifest, variant_paths=variants)
    snapshot = fetch_source(SOURCES[manifest["benchmark"]], cache)
    if manifest["revision"] != snapshot.spec.revision:
        raise ValueError("任务版本与预注册不同")
    for task in manifest["tasks"]:
        path = snapshot.tasks_path / task["task_id"]
        if not path.resolve().is_relative_to(snapshot.tasks_path.resolve()):
            raise ValueError("任务路径越界")
        if sha256_file(path / "task.toml") != task["config_sha256"]:
            raise ValueError("官方资源配置已变化")
        if sha256_file(path / "instruction.md") != task["instruction_sha256"]:
            raise ValueError("官方题面已变化")
    output.mkdir(parents=True, exist_ok=True)
    copied = output / "manifest.json"
    if copied.exists():
        if file_sha256(copied) != file_sha256(manifest_path):
            raise ValueError("已有结果目录属于另一份清单")
    else:
        shutil.copyfile(manifest_path, copied)
    if (output / "abort.json").exists():
        raise ValueError("已中止实验不能覆盖恢复；请保留旧结果并建立复验批次")
    return manifest, snapshot.tasks_path, snapshot.path / "v2" / "tooling"


async def run_phase(
    manifest_path: Path,
    output: Path,
    cache: Path,
    wheel: Path,
    requirements: Path,
    variants: dict[str, Path],
    connections: dict[str, Path],
    private_home: Path,
    *,
    continuation: PhaseContinuation | None = None,
) -> dict[str, Any]:
    """一任务块内固定接口；跨块互备由冻结清单声明，失败记录不覆盖。"""
    validate_directories(output, cache, wheel, requirements, private_home)
    if any(path.resolve().is_relative_to(output.resolve()) for path in connections.values()):
        raise ValueError("原始私有连接文件不能位于结果归档目录")
    if {path.resolve() for path in variants.values()} & {
        path.resolve() for path in connections.values()
    }:
        raise ValueError("公开候选与私有连接不能共用文件")
    manifest, tasks_root, tooling = _prepare(
        manifest_path, output, cache, wheel, requirements, variants
    )
    output = output.resolve()
    records_path = output / "records.jsonl"
    records = _records(records_path)
    policy, prior_records = _paid_inputs(manifest)
    if policy is not None and any(
        Path(reference["path"]).resolve() == records_path.resolve()
        for reference in policy["prior_records"]
    ):
        raise ValueError("本阶段活动记录不能同时作为冻结的历史费用记录")
    schedule = paired_order(manifest)
    continuation_identity = None
    if continuation is not None:
        if not isinstance(continuation, PhaseContinuation):
            raise ValueError("continuation 必须使用冻结的 PhaseContinuation")
        records, additional_paid, continuation_identity = _continue_phase(
            manifest, schedule, records, continuation
        )
        if additional_paid and policy is None:
            raise ValueError("追加跨阶段费用必须有 master 冻结的 paid_budget")
        prior_records = [*prior_records, *additional_paid]
    remaining = remaining_order(manifest, records)
    if continuation is not None:
        remaining = [item for item in remaining if item["sequence"] in continuation.sequences]
    connection_order = manifest.get("connections", ["local"])
    if set(connection_order) - connections.keys():
        raise ValueError("缺少预注册接口的私有配置")
    request_identity = {
        "manifest": file_sha256(manifest_path),
        "artifact": file_sha256(wheel),
        "requirements": file_sha256(requirements),
        "variants": {name: file_sha256(path) for name, path in variants.items()},
        "implementation": implementation_identity(),
        "profiles": {
            label: {key: value for key, value in read_json(path).items() if key != "api_key"}
            for label, path in connections.items()
        },
    }
    if continuation_identity is not None:
        request_identity["continuation"] = continuation_identity
    identity_file = output / "identity.json"
    if identity_file.exists():
        if read_json(identity_file) != request_identity:
            raise ValueError("恢复输入身份已变化，不能混用旧结果")
    else:
        write_json(identity_file, request_identity, exclusive=True)
    if continuation is not None:
        _save_records(records_path, records)
    variants_dir = private_home / "runs" / output.name
    variants_dir.mkdir(parents=True, exist_ok=True)
    require_replay = manifest["benchmark"] == "swe-bench-pro-v2"
    try:
        for item in remaining:
            if shutil.disk_usage(output.anchor).free < 12 * 1024**3:
                record_stop(output, "insufficient_disk_headroom")
                break
            reason = _paid_stop_reason(
                policy, records, prior_records, manifest=manifest
            ) or check_budget(records, reported_token_limit=int(manifest["reported_token_limit"]))
            if reason:
                record_stop(output, reason)
                break
            index = schedule.index(item)
            task_id, label, repeat = item["task_id"], item["configuration"], item["repeat"]
            endpoint = connection_order[(repeat - 1) % len(connection_order)]
            connection = read_connection(endpoint, connections[endpoint])
            profile = read_json(connection.profile_path)
            public_profile = {key: value for key, value in profile.items() if key != "api_key"}
            expected_profile = manifest.get("connection_profiles", {}).get(endpoint)
            if expected_profile is not None and public_profile != expected_profile:
                raise ValueError("连接的模型参数与冻结清单不一致")
            if profile["protocol"] != "anthropic_messages":
                raise ValueError("本次校准后的正式连接必须统一使用 Messages 协议")
            upstream = messages_endpoint(profile["base_url"])
            task_definition = next(task for task in manifest["tasks"] if task["task_id"] == task_id)
            mode = (
                task_definition.get("agent", {}).get("network_mode")
                or task_definition.get("environment", {}).get("network_mode")
                or "public"
            )
            # PUBLIC 沿用原始模型地址；内部网关别名只在受限 Agent 网络可达。
            if mode != "public":
                profile["base_url"] = "http://saya-model-gateway:8080"
            private_profile = variants_dir / f"{endpoint}-gateway.json"
            write_json(private_profile, profile)
            private_profile.chmod(0o600)
            agent = AgentConfig(
                import_path="sayacode_bench.adapter:SayacodeAgent",
                model_name=CANONICAL_MODEL,
                extra_allowed_hosts=["saya-model-gateway"],
                kwargs={
                    "product_wheel": str(wheel),
                    "requirements_path": str(requirements),
                    "profile_path": str(private_profile),
                    "variant_path": str(variants[label]),
                },
            )
            environment = EnvironmentConfig(
                import_path="sayacode_bench.network:IsolatedDockerEnvironment",
                kwargs={"messages_upstream": upstream},
            )
            job_name = f"{manifest['phase']}-{index + 1:04}-{label}-{repeat}"
            write_json(
                output / "progress.json",
                {
                    "active": item,
                    "completed": len(records),
                    "planned": len(schedule),
                    "endpoint": endpoint,
                },
            )
            print(f"[{len(records) + 1}/{len(schedule)}] {label} #{repeat} {task_id}", flush=True)
            record = await run_official_trial(
                tasks_root / task_id,
                output / "jobs",
                job_name,
                agent,
                environment,
                configuration=label,
                repeat=repeat,
                endpoint=endpoint,
                require_replay=require_replay,
            )
            # 源试验已经消耗模型资源；重判失败也不能让它从总表和预算消失。
            records.append({**record, "record_complete": not require_replay})
            _save_records(records_path, records)
            if require_replay:
                record = await replay_official_trial(
                    tasks_root / task_id,
                    output / "replays",
                    job_name + "-replay",
                    Path(record["job_dir"]),
                    tooling,
                    environment,
                )
            records[-1] = record
            _save_records(records_path, records)
            summary = phase_summary(manifest, records, prior_records=prior_records)
            write_json(output / "summary.json", summary)
            if policy is not None:
                write_json(output / "budget.json", summary["paid_budget"])
            print(
                f"  status={record['status']} success={record['success']} "
                f"verified={record['verified']}",
                flush=True,
            )
            if manifest.get("runtime_evidence_required") is True and not _runtime_confirmed(
                record,
                replay=require_replay,
                qualified=manifest.get("qualified_runtime_identities", {}).get(task_id),
                task_environment=task_definition.get("environment", {}),
            ):
                record_stop(output, "runtime_evidence_unconfirmed")
                break
            # 外部故障使本批次失效，最后一项也要留证；资源阈值只阻止新派发。
            fatal = fatal_stop_reason(records)
            if fatal:
                record_stop(output, fatal)
                break
            reason = _paid_stop_reason(policy, records, prior_records, manifest=manifest)
            if reason and item != remaining[-1]:
                record_stop(output, reason)
                break
    except BaseException as exc:
        if not (output / "abort.json").exists():
            record_stop(output, "execution_interrupted", details={"error_type": type(exc).__name__})
        raise
    finally:
        summary = phase_summary(
            report_manifest(manifest, output), records, prior_records=prior_records
        )
        write_json(output / "summary.json", summary)
        if policy is not None:
            write_json(output / "budget.json", summary["paid_budget"])
        write_json(
            output / "progress.json",
            {"completed": len(records), "planned": len(schedule), "active": None},
        )
    return summary
