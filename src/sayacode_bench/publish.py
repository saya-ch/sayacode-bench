"""从完整原始记录生成可公开的白名单结果，不复制轨迹或私有连接。"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .artifacts import file_sha256, read_json, report_manifest, write_json
from .connections import CANONICAL_MODEL
from .study import phase_summary

_EVIDENCE = (
    "raw_job_result",
    "raw_trial_result",
    "worker_result",
    "replay_raw_trial_result",
    "patch",
    "runtime",
    "replay_runtime",
    "network_isolation",
    "replay_network_isolation",
)
_TASK_FIELDS = (
    "task_id",
    "benchmark",
    "revision",
    "repository",
    "language",
    "category",
    "difficulty",
    "leakage_group",
    "instruction_sha256",
    "config_sha256",
    "task_tree_sha256",
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PRIVATE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|(?:Bearer\s+)[A-Za-z0-9._-]{16,}", re.IGNORECASE)
_PRIVATE_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "secret",
        "secretkey",
        "password",
        "passwd",
        "credential",
        "credentials",
        "accesstoken",
        "refreshtoken",
        "token",
        "privatekey",
        "clientsecret",
    }
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_USER_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|"
    r"(?<![A-Za-z0-9:/])/(?!\s|$)[^\s<>\"']+",
    re.IGNORECASE,
)
_RECORD_STRINGS = frozenset(
    {
        "task_id",
        "configuration",
        "canonical_model",
        "endpoint",
        "status",
        "worker_status",
        "verification_kind",
        "replay_status",
        "patch_application",
        "failure_category",
        "harbor_exception_type",
        "recorded_at",
        "request_sha256",
        "official_tooling_sha256",
    }
)
_RECORD_INTEGERS = frozenset(
    {"repeat", "apply_rc", "input_tokens", "output_tokens", "task_count", "terminal_http_status"}
)
_RECORD_BOOLEANS = frozenset({"success", "verified", "usage_complete", "record_complete"})
_RECORD_NUMBERS = frozenset(
    {
        "original_reward",
        "replay_reward",
        "duration_seconds",
        "original_duration_seconds",
        "replay_duration_seconds",
    }
)
_RECORD_LISTS = frozenset({"child_roles", "terminal_error_types", "normalization_issues"})
_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "phase",
        "canonical_model",
        "tasks",
        "repositories",
        "repeats",
        "formal_comparison_eligible",
        "formal_validation_eligible",
        "final_result_eligible",
        "conclusion_scope",
        "validity_issues",
        "missing_trials",
        "endpoint_counts",
        "endpoint_mismatches",
        "groups",
        "task_success_rates",
        "comparison",
        "cautions",
        "paid_budget",
    }
)


def validate_public(value: Any) -> None:
    """发布前统一递归检查；不以密钥必须带特定前缀为假设。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("公开对象的键必须是字符串")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in _PRIVATE_KEYS:
                raise ValueError("公开对象包含凭据字段")
            validate_public(key)
            validate_public(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_public(item)
    elif isinstance(value, str):
        for match in _URL.finditer(value):
            url = urlsplit(match[0])
            query_keys = {re.sub(r"[^a-z0-9]", "", key.lower()) for key, _ in parse_qsl(url.query)}
            if url.username is not None or url.password is not None or query_keys & _PRIVATE_KEYS:
                raise ValueError("公开 URL 包含疑似凭据")
        if _PRIVATE.search(value) or _USER_PATH.search(_URL.sub("", value)):
            raise ValueError("公开对象包含疑似凭据或用户路径")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("公开数值必须有限")
    elif value is not None and type(value) not in {bool, int, float}:
        raise ValueError("公开对象必须能无损表示为 JSON")


def _scalar(value: Any, kind: type[Any]) -> Any:
    if value is None:
        return None
    valid = type(value) in {int, float} if kind is float else type(value) is kind
    if not valid or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("公开字段类型不符合约定")
    return value


def _list(value: Any, kind: type[Any] = str) -> list[Any] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("公开列表字段类型无效")
    if any(item is None for item in value):
        raise ValueError("公开列表元素不能用未知值代替")
    return [_scalar(item, kind) for item in value]


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("公开结构字段必须是对象")
    return value


def _fields(source: dict[str, Any], names: Iterable[str], kind: type[Any]) -> dict[str, Any]:
    return {name: _scalar(source[name], kind) for name in names if name in source}


def _digest(value: Any) -> str | None:
    if value is not None and (not isinstance(value, str) or not _DIGEST.fullmatch(value)):
        raise ValueError("证据身份必须是 SHA256")
    return value


def _hashes(value: Any) -> dict[str, str | None]:
    return {key: _digest(item) for key, item in _object(value).items()}


def _runtime(value: Any) -> dict[str, Any]:
    source = _object(value)
    if type(source.get("available")) is not bool:
        raise ValueError("运行环境身份必须明确观测是否可用")
    result = {
        **_fields(source, ("available", "storage_hard_limit_supported"), bool),
        **_fields(source, ("reason", "image_id", "architecture", "os"), str),
    }
    if "repo_digests" in source:
        result["repo_digests"] = _list(source["repo_digests"])
    if source.get("requested") is not None:
        requested = _object(source["requested"])
        result["requested"] = {
            **_fields(requested, ("cpus", "memory_mb", "storage_mb"), int),
            **_fields(requested, ("docker_image",), str),
        }
    if source.get("docker_limits") is not None:
        limits = _object(source["docker_limits"])
        selected = _fields(
            limits, ("NanoCpus", "CpuPeriod", "CpuQuota", "Memory", "MemorySwap"), int
        )
        if "StorageOpt" in limits:
            storage = limits["StorageOpt"]
            selected["StorageOpt"] = (
                None if storage is None else _fields(_object(storage), ("size",), str)
            )
        result["docker_limits"] = selected
    if source.get("cgroup_v2") is not None:
        result["cgroup_v2"] = _fields(
            _object(source["cgroup_v2"]), ("cpu.max", "memory.max", "memory.swap.max"), str
        )
    return result


def _profile(value: Any) -> dict[str, Any]:
    source = _object(value)
    result = {
        **_fields(source, ("protocol", "model_id"), str),
        **_fields(
            source,
            (
                "context_length",
                "max_output_tokens",
                "summary_trigger_tokens",
                "summary_keep_messages",
                "context_edit_trigger",
                "model_retries",
                "tool_retries",
                "tool_selector_max_tools",
            ),
            int,
        ),
        **_fields(source, ("summary_trigger_ratio",), float),
        **_fields(source, ("file_search",), bool),
    }
    if "native_tool_search_tools" in source:
        result["native_tool_search_tools"] = _list(source["native_tool_search_tools"])
    return result


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """保留可重算统计和证据哈希；任意新增私有字段默认不进入发布物。"""
    if record.get("canonical_model") != CANONICAL_MODEL:
        raise ValueError("公开记录的规范模型与研究不一致")
    result = {
        **_fields(record, _RECORD_STRINGS, str),
        **_fields(record, _RECORD_INTEGERS, int),
        **_fields(record, _RECORD_BOOLEANS, bool),
        **_fields(record, _RECORD_NUMBERS, float),
    }
    for key in _RECORD_LISTS:
        if key in record:
            result[key] = _list(record[key])
    if "terminal_http_statuses" in record:
        result["terminal_http_statuses"] = _list(record["terminal_http_statuses"], int)
    for key in ("runtime_identity", "replay_runtime_identity"):
        if key in record:
            result[key] = _runtime(record[key])
    if "runtime_comparison" in record:
        result["runtime_comparison"] = _fields(
            _object(record["runtime_comparison"]),
            ("same_image", "same_platform", "same_resources"),
            bool,
        )
    # usage 的字段也显式限定，防止提供商原始响应混入。
    usage = record.get("usage", {})
    result["usage"] = _fields(
        _object(usage),
        (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "model_calls",
            "reported_calls",
            "missing_usage_calls",
            "damaged_audit_lines",
        ),
        int,
    )
    if "cost_usd" in usage:
        result["usage"]["cost_usd"] = _scalar(usage["cost_usd"], float)
    evidence = {}
    for key in _EVIDENCE:
        value = record.get(key)
        digest = value.get("sha256") if isinstance(value, dict) else None
        evidence[key] = {"sha256": _digest(digest)}
    result["evidence"] = evidence
    validate_public(result)
    return result


def export_results(manifest_path: Path, records_path: Path, output: Path) -> dict[str, Any]:
    """新建独立发布目录；不把开发或中止批次升级为正式比较。"""
    if output.exists():
        raise ValueError("发布目录已存在，不能覆盖旧的公开身份")
    manifest = report_manifest(read_json(manifest_path), records_path.parent)
    records = [
        json.loads(row) for row in records_path.read_text(encoding="utf-8").splitlines() if row
    ]
    sanitized = [public_record(row) for row in records]
    report = {
        key: value
        for key, value in phase_summary(manifest, sanitized).items()
        if key in _REPORT_FIELDS
    }
    budget = report.get("paid_budget")
    if isinstance(budget, dict):
        for key in ("price_snapshot", "prior_records"):
            references = budget.get(key)
            if isinstance(references, dict):
                budget[key] = {"sha256": references.get("sha256")}
            elif isinstance(references, list):
                budget[key] = [{"sha256": item.get("sha256")} for item in references]
    public_manifest: dict[str, Any] = {
        **_fields(manifest, ("schema_version", "repeats", "reported_token_limit"), int),
        **_fields(manifest, ("frozen", "preflight_passed", "runtime_evidence_required"), bool),
        **_fields(
            manifest,
            (
                "phase",
                "canonical_model",
                "benchmark",
                "revision",
                "seed",
                "baseline",
                "candidate",
                "selection_sha256",
                "scope",
            ),
            str,
        ),
    }
    for key in ("configurations", "connections"):
        if key in manifest:
            public_manifest[key] = _list(manifest[key])
    public_manifest["validity_issues"] = sorted(
        set([*(manifest.get("validity_issues") or []), *(report.get("validity_issues") or [])])
    )
    if "preflight" in manifest:
        preflight = _object(manifest["preflight"])
        public_manifest["preflight"] = {
            key: _digest(preflight[key])
            for key in ("sanity_sha256", "network_probe_sha256")
            if key in preflight
        }
    if "artifacts" in manifest:
        artifacts = _object(manifest["artifacts"])
        public_manifest["artifacts"] = {
            key: _digest(artifacts[key])
            for key in ("product_wheel", "requirements")
            if key in artifacts
        }
        if "variants" in artifacts:
            public_manifest["artifacts"]["variants"] = _hashes(artifacts["variants"])
    if "implementation" in manifest:
        public_manifest["implementation"] = _hashes(manifest["implementation"])
    if "qualified_runtime_identities" in manifest:
        public_manifest["qualified_runtime_identities"] = {
            task_id: _runtime(identity)
            for task_id, identity in _object(manifest["qualified_runtime_identities"]).items()
        }
    public_manifest["tasks"] = []
    for row in manifest["tasks"]:
        task = _fields(_object(row), _TASK_FIELDS, str)
        if row.get("environment") is not None:
            environment = _object(row["environment"])
            task["environment"] = {
                **_fields(environment, ("cpus", "memory_mb", "storage_mb"), int),
                **_fields(environment, ("docker_image",), str),
            }
        public_manifest["tasks"].append(task)
    public_manifest["connection_profiles"] = {
        alias: _profile(profile)
        for alias, profile in manifest.get("connection_profiles", {}).items()
    }
    receipt = manifest.get("candidate_receipt")
    if isinstance(receipt, dict):
        public_manifest["candidate_receipt_sha256"] = _digest(receipt.get("sha256"))
    public_manifest["raw_identity"] = {
        "manifest_sha256": file_sha256(manifest_path),
        "records_sha256": file_sha256(records_path),
    }
    public_manifest["evidence_scope"] = (
        "白名单事实与原始工件哈希；完整轨迹、检查点、私有连接及原始绝对路径不公开。"
        "哈希用于来源关联，不构成独立认证；第三方应依冻结输入重新执行。"
    )
    validate_public(public_manifest)
    validate_public(report)
    # 全部数据验证后再新建，避免失败时留下看似已完成的发布目录。
    output.mkdir(parents=True)
    write_json(output / "manifest.json", public_manifest, exclusive=True)
    with (output / "records.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
        for row in sanitized:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(output / "analysis.json", report, exclusive=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_results(args.manifest, args.records, args.output)


if __name__ == "__main__":
    main()
