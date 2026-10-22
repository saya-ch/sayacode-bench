"""按冻结清单执行研究阶段，所有任务执行和判分交给 Harbor。"""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

from harbor.models.trial.config import AgentConfig, EnvironmentConfig

from .analysis import analyze_experiment
from .artifacts import (
    check_budget,
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
from .sources import SOURCES, fetch_source, sha256_file


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
    return {
        "paid_endpoints": tuple(policy["paid_endpoints"]),
        "input_cny_per_million": policy["input_cny_per_million"],
        "output_cny_per_million": policy["output_cny_per_million"],
    }


def _check_budget_references(policy: dict[str, Any]) -> None:
    references = [policy["price_snapshot"], *policy["prior_records"]]
    for reference in references:
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ValueError("费用证据身份格式无效")
        path = Path(reference["path"]).resolve(strict=True)
        if file_sha256(path) != reference.get("sha256"):
            raise ValueError("已冻结的价格或历史费用记录发生变化")


def _paid_inputs(manifest: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    policy = manifest.get("paid_budget")
    if policy is None:
        return None, []
    if not isinstance(policy, dict) or not isinstance(policy.get("prior_records"), list):
        raise ValueError("paid_budget 必须包含冻结的历史记录列表")
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
    paid_endpoints: list[str] | None = None,
) -> dict[str, Any] | None:
    """只冻结显式授权的金额；价格和全部先前阶段记录以路径及内容哈希绑定。"""
    if limit_cny is None:
        if price_snapshot is not None or prior_records or paid_endpoints or stop_fraction != 0.8:
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
    _paid_inputs({"paid_budget": policy})
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
    policy: dict[str, Any] | None, records: list[dict[str, Any]], prior: list[dict[str, Any]]
) -> str | None:
    if policy is None:
        return None
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
        if budget and not budget["evidence_valid"]:
            summary["validity_issues"] = sorted(
                set([*summary["validity_issues"], "paid_budget_evidence_invalid"])
            )
            for field in (
                "formal_comparison_eligible",
                "formal_validation_eligible",
                "final_result_eligible",
            ):
                summary[field] = False
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
    record: dict[str, Any], *, replay: bool, qualified: dict[str, Any] | None = None
) -> bool:
    """正式试验逐次核实实际镜像身份，不用同名 tag 替代证据。"""
    identity = record.get("runtime_identity")
    if not isinstance(identity, dict) or identity.get("available") is not True:
        return False
    if not identity.get("image_id") or not identity.get("architecture") or not identity.get("os"):
        return False
    if qualified is not None and any(
        identity.get(key) != qualified.get(key) for key in ("image_id", "architecture", "os")
    ):
        return False
    if replay:
        comparison = record.get("runtime_comparison", {})
        return (
            isinstance(comparison, dict)
            and comparison.get("same_image") is True
            and comparison.get("same_platform") is True
        )
    return True


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
    remaining = remaining_order(manifest, records)
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
    identity_file = output / "identity.json"
    if identity_file.exists():
        if read_json(identity_file) != request_identity:
            raise ValueError("恢复输入身份已变化，不能混用旧结果")
    else:
        write_json(identity_file, request_identity, exclusive=True)
    variants_dir = private_home / "runs" / output.name
    variants_dir.mkdir(parents=True, exist_ok=True)
    require_replay = manifest["benchmark"] == "swe-bench-pro-v2"
    try:
        for item in remaining:
            if shutil.disk_usage(output.anchor).free < 12 * 1024**3:
                record_stop(output, "insufficient_disk_headroom")
                break
            reason = _paid_stop_reason(policy, records, prior_records) or check_budget(
                records, reported_token_limit=int(manifest["reported_token_limit"])
            )
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
            ):
                record_stop(output, "runtime_evidence_unconfirmed")
                break
            reason = _paid_stop_reason(policy, records, prior_records)
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
