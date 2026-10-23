"""显式核销已核对的历史账单；不修改原用量，也不豁免后续未知费用。"""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import posixpath
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _money(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("历史核销金额必须使用十进制字符串")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("历史核销金额格式无效") from error
    if not result.is_finite() or result <= 0 or not math.isfinite(float(result)):
        raise ValueError("历史核销金额必须为正有限数")
    return result


def _checked_bytes(reference: Any, base: Path | None = None) -> tuple[bytes, Path]:
    if (
        not isinstance(reference, Mapping)
        or not isinstance(reference.get("path"), str)
        or not reference["path"]
        or not isinstance(reference.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None
    ):
        raise ValueError("历史核销缺少文件路径与完整 SHA256")
    path = Path(reference["path"])
    if base is not None:
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("核销证据必须在收据目录内使用相对路径")
        path = base / path
    path = path.resolve(strict=True)
    if base is not None and not path.is_relative_to(base.resolve(strict=True)):
        raise ValueError("核销证据不能通过符号链接越出收据目录")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise ValueError("已冻结的历史核销证据发生变化")
    return content, path


def _object(content: bytes) -> dict[str, Any]:
    value = json.loads(content.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("历史核销证据必须为 JSON 对象")
    return value


def _complete(row: Mapping[str, Any]) -> bool:
    usage = row.get("usage")
    if not isinstance(usage, Mapping):
        return False
    return (
        row.get("usage_complete") is True
        and all(
            type(row.get(key)) is int and row[key] >= 0 for key in ("input_tokens", "output_tokens")
        )
        and all(
            type(usage.get(key)) is int and usage[key] >= 0
            for key in (
                "model_calls",
                "reported_calls",
                "missing_usage_calls",
                "damaged_audit_lines",
            )
        )
        and usage["model_calls"] == usage["reported_calls"]
        and usage["missing_usage_calls"] == usage["damaged_audit_lines"] == 0
    )


def _job_alias(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("历史核销路径别名必须为非空字符串")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(value))
    return posixpath.normpath(value)


def historical_settlement(
    reference: Mapping[str, Any] | None,
    records: Iterable[Mapping[str, Any]] = (),
    *,
    paid_endpoints: tuple[str, ...] = ("remote",),
) -> tuple[Decimal, dict[str, Any] | None]:
    """每次派发和报告都重验原件；仅返回可以公开的金额、哈希和证据边界。"""
    if reference is None:
        return Decimal(0), None
    content, path = _checked_bytes(reference)
    receipt = _object(content)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "historical_supplier_ui_settlement"
        or receipt.get("currency") != "CNY"
        or type(receipt.get("raw_usage_complete")) is not bool
        or receipt.get("future_missing_usage_allowed") is not False
    ):
        raise ValueError("历史核销收据类型或证据边界无效")
    amount = _money(receipt.get("amount_cny"))
    limit = _money(receipt.get("budget_limit_cny"))
    start = receipt.get("budget_start_utc")
    if not isinstance(start, str) or datetime.fromisoformat(start).utcoffset() is None:
        raise ValueError("历史核销必须明确含时区的原预算起点")
    if amount > limit:
        raise ValueError("历史核销金额超过原总预算")
    bill_content, _ = _checked_bytes(receipt.get("billing_evidence"), path.parent)
    bill = _object(bill_content)
    auth_content, _ = _checked_bytes(receipt.get("authorization"), path.parent)
    auth = _object(auth_content)
    if (
        bill.get("kind") != "supplier_ui_read_only_billing_reconciliation"
        or bill.get("budget_start_utc") != start
        or bill.get("original_calibration_records_modified") is not False
        or bill.get("per_failure_zero_charge_guarantee") is not False
        or amount != _money(bill.get("candidate_conservative_historical_budget_debit_cny"))
        or amount < _money(bill.get("calculated_nominal_cny_from_displayed_units_and_rates"))
        or amount < _money(bill.get("displayed_entire_date_range_nominal_cny"))
    ):
        raise ValueError("历史核销与账单核对范围或保守金额不一致")
    if (
        auth.get("schema_version") != 1
        or auth.get("kind") != "user_authorized_historical_settlement"
        or auth.get("confirmation") != "均同意"
        or auth.get("budget_start_utc") != start
        or _money(auth.get("budget_limit_cny")) != limit
        or _money(auth.get("amount_cny")) != amount
        or auth.get("billing_sha256") != receipt["billing_evidence"]["sha256"]
        or auth.get("original_usage_unknown_preserved") is not True
        or auth.get("future_missing_usage_allowed") is not False
    ):
        raise ValueError("历史核销缺少对应金额、范围与证据边界的明确授权")
    sources = receipt.get("records")
    bill_sources = bill.get("sources")
    if not isinstance(sources, list) or not sources or not isinstance(bill_sources, list):
        raise ValueError("历史核销必须绑定原始逐次记录")
    requests: set[str] = set()
    file_hashes: set[str] = set()
    jobs: set[str] = set()
    original: list[dict[str, Any]] = []
    for source in sources:
        raw, _ = _checked_bytes(source, path.parent)
        rows = [_object(line) for line in raw.splitlines() if line.strip()]
        # 每个独立历史请求使用自己的原始记录；不按冲突的旧 VM 路径合并。
        if len(rows) != 1:
            raise ValueError("每份历史核销原件必须恰好包含一个原始请求")
        row = rows[0]
        request = row.get("request_sha256")
        if (
            not isinstance(request, str)
            or re.fullmatch(r"[0-9a-f]{64}", request) is None
            or source.get("request_sha256") != request
            or row.get("record_complete") is not True
            or row.get("endpoint") not in paid_endpoints
        ):
            raise ValueError("历史原件请求身份、收尾状态或付费连接不匹配")
        if request in requests or source["sha256"] in file_hashes:
            raise ValueError("同一历史请求不能重复核销")
        matching = [
            item
            for item in bill_sources
            if isinstance(item, dict) and item.get("request_sha256") == request
        ]
        if (
            len(matching) != 1
            or matching[0].get("record_sha256") != source["sha256"]
            or matching[0].get("source_usage") != row.get("usage")
        ):
            raise ValueError("账单核对未绑定该原始记录及真实用量")
        requests.add(request)
        file_hashes.add(source["sha256"])
        original.append(row)
        jobs.update(
            alias
            for key in ("source_job", "job_dir")
            if (alias := _job_alias(row.get(key))) is not None
        )
    if (
        len(bill_sources) != len(requests)
        or auth.get("request_sha256s") != sorted(requests)
        or receipt["raw_usage_complete"] is not all(_complete(row) for row in original)
    ):
        raise ValueError("核销请求范围或原始用量完整性声明不一致")
    # 路径别名也保守拒绝；新执行应已有唯一的 run/job 命名空间。
    for current in records:
        if not isinstance(current, Mapping):
            raise ValueError("每条试验用量记录必须是对象")
        if current.get("request_sha256") in requests or any(
            _job_alias(current.get(key)) in jobs for key in ("source_job", "job_dir")
        ):
            raise ValueError("已核销历史请求不能再次进入当前或 prior token 费用")
    return amount, {
        "receipt_sha256": reference["sha256"],
        "billing_sha256": receipt["billing_evidence"]["sha256"],
        "authorization_sha256": receipt["authorization"]["sha256"],
        "record_sha256s": sorted(file_hashes),
        "request_sha256s": sorted(requests),
        "amount_cny": float(amount),
        "budget_limit_cny": float(limit),
        "budget_start_utc": start,
        "raw_usage_complete": receipt["raw_usage_complete"],
        "future_missing_usage_allowed": False,
        "supplier_signed": False,
        "evidence_kind": "user_authorized_read_only_supplier_ui_reconciliation",
    }
