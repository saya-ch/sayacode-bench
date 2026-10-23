"""对已报告的付费连接用量估价，并在任务边界停止派发；不冒充供应商账单。"""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

Record = Mapping[str, Any]
Rate = int | float | Decimal


def _amount(value: Rate, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} 必须是有限数")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or positive and result == 0:
        raise ValueError(f"{name} 必须是{'正' if positive else '非负'}有限数")
    return result


def _counter(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} 必须是非负整数或 null")
    return value


def _path_identity(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空路径字符串")
    # 不访问文件系统；Windows 的斜杠与大小写写法仍指向同一份 job。
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(value))
    return posixpath.normpath(value)


@dataclass(frozen=True)
class _Usage:
    endpoint: str
    input_tokens: int | None
    output_tokens: int | None
    complete: bool
    model_calls: int | None
    missing_calls: int | None
    fingerprint: str
    cache_usage: Any
    usage_details: Any


def _usage(record: Record) -> _Usage:
    endpoint = record.get("endpoint")
    if not isinstance(endpoint, str) or re.fullmatch(r"[A-Za-z0-9_-]+", endpoint) is None:
        raise ValueError("endpoint 必须是非秘密连接别名")
    input_tokens = _counter(record.get("input_tokens"), "input_tokens")
    output_tokens = _counter(record.get("output_tokens"), "output_tokens")
    flag = record.get("usage_complete")
    if flag is not None and type(flag) is not bool:
        raise ValueError("usage_complete 必须是 bool 或 null")
    raw = record.get("usage")
    if raw is not None and not isinstance(raw, Mapping):
        raise ValueError("usage 必须是对象或 null")
    raw = raw or {}
    counters = {
        key: _counter(raw.get(key), f"usage.{key}")
        for key in ("model_calls", "reported_calls", "missing_usage_calls", "damaged_audit_lines")
    }
    calls, reported = counters["model_calls"], counters["reported_calls"]
    missing, damaged = counters["missing_usage_calls"], counters["damaged_audit_lines"]
    if calls is not None and reported is not None and reported > calls:
        raise ValueError("reported_calls 不能大于 model_calls")
    if calls is not None and missing is not None and missing > calls:
        raise ValueError("missing_usage_calls 不能大于 model_calls")
    coverage_known = all(value is not None for value in counters.values())
    complete = (
        flag is True
        and input_tokens is not None
        and output_tokens is not None
        and coverage_known
        and missing == 0
        and damaged == 0
        and calls == reported
    )
    if complete:
        missing_calls: int | None = 0
    elif not coverage_known or damaged:
        # 缺失计数和损坏行均可能隐藏未观察到的调用，不能补成零缺失。
        missing_calls = None
    elif calls is not None and reported is not None:
        missing_calls = max(missing or 0, calls - reported)
    else:
        missing_calls = missing
    facts = {
        "endpoint": endpoint,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usage_complete": flag,
        "counters": counters,
        **{
            key: record.get(key)
            for key in ("task_id", "configuration", "repeat", "canonical_model")
        },
        "cache_usage": record.get("cache_usage"),
        "usage_details": record.get("usage_details"),
    }
    fingerprint = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _Usage(
        endpoint,
        input_tokens,
        output_tokens,
        complete,
        calls,
        missing_calls,
        fingerprint,
        record.get("cache_usage"),
        record.get("usage_details"),
    )


def _observed_cache(row: _Usage) -> tuple[str, int]:
    """只认已由原生旁证核验的缓存读取；写入费率未知时不能算完整费用。"""
    cache = row.cache_usage
    if cache is None:
        return "unavailable", 0
    if not isinstance(cache, Mapping) or cache.get("status") not in {
        "complete",
        "unavailable",
        "invalid",
    }:
        return "invalid", 0
    try:
        creation = _counter(cache.get("cache_creation_input_tokens"), "cache_creation_input_tokens")
        read = _counter(cache.get("cache_read_input_tokens"), "cache_read_input_tokens")
        if cache["status"] == "invalid" or creation and creation > 0:
            return "invalid", 0
        if not row.complete:
            return "unavailable", 0
        counts = {
            key: _counter(cache.get(key), "cache_usage." + key)
            for key in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "model_calls",
                "matched_calls",
            )
        }
        if (
            counts["input_tokens"] is not None
            and counts["input_tokens"] != row.input_tokens
            or counts["output_tokens"] is not None
            and counts["output_tokens"] != row.output_tokens
            or counts["model_calls"] is not None
            and counts["model_calls"] != row.model_calls
            or counts["total_tokens"] is not None
            and row.input_tokens is not None
            and row.output_tokens is not None
            and counts["total_tokens"] != row.input_tokens + row.output_tokens
            or read is not None
            and row.input_tokens is not None
            and read > row.input_tokens
        ):
            return "invalid", 0
        if (
            cache["status"] != "complete"
            or cache.get("coverage_complete") is not True
            or read is None
            or creation is None
            or any(value is None for value in counts.values())
        ):
            return "unavailable", 0
        if counts["matched_calls"] != counts["model_calls"]:
            return "invalid", 0
        reference = row.usage_details
        if (
            cache.get("collector") != "langchain_callback_usage_v1"
            or not isinstance(cache.get("audit_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", cache["audit_sha256"]) is None
            or not isinstance(reference, Mapping)
            or not isinstance(reference.get("path"), str)
            or not reference["path"]
            or not isinstance(reference.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None
        ):
            return "unavailable", 0
        # 新策略的优惠还要求旁证文件仍可重验；缺失时退回全输入价。
        sidecar = Path(reference["path"])
        for path, expected in (
            (sidecar, reference["sha256"]),
            (sidecar.with_name("audit.jsonl"), cache["audit_sha256"]),
        ):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024**2):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                return "invalid", 0
        return "complete", read
    except OSError:
        return "unavailable", 0
    except (ValueError, TypeError):
        return "invalid", 0


def _unique_usage(records: Iterable[Record]) -> tuple[list[_Usage], int]:
    values: list[_Usage] = []
    aliases: dict[tuple[str, str], int] = {}
    requests: dict[int, str | None] = {}
    duplicates = 0
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("每条试验用量记录必须是对象")
        usage = _usage(record)
        identities: set[tuple[str, str]] = set()
        for field in ("source_job", "job_dir"):
            path = _path_identity(record.get(field), field)
            if path is not None:
                identities.add(("job", path))
        request = record.get("request_sha256")
        if request is not None:
            if not isinstance(request, str) or re.fullmatch(r"[0-9a-f]{64}", request) is None:
                raise ValueError("request_sha256 必须是完整小写 SHA256")
            identities.add(("request", request))
        if not identities:
            raise ValueError("用量记录缺少 source_job、job_dir 或 request_sha256 执行身份")
        existing = {aliases[identity] for identity in identities if identity in aliases}
        if len(existing) > 1:
            raise ValueError("同一记录关联了两个已经独立计量的执行身份")
        if existing:
            index = existing.pop()
            if requests[index] is not None and request is not None and requests[index] != request:
                raise ValueError("同一执行路径的 request_sha256 冲突")
            if values[index].fingerprint != usage.fingerprint:
                raise ValueError("重复执行身份的用量或连接事实冲突")
            duplicates += 1
        else:
            index = len(values)
            values.append(usage)
            requests[index] = request
        if requests[index] is None and request is not None:
            requests[index] = request
        for identity in identities:
            aliases[identity] = index
    return values, duplicates


def _estimate(
    records: Iterable[Record],
    paid_endpoints: tuple[str, ...],
    input_rate: Decimal,
    output_rate: Decimal,
    pricing_method: str,
    cache_read_rate: Decimal,
) -> tuple[dict[str, Any], Decimal]:
    if (
        not isinstance(paid_endpoints, (tuple, list))
        or not paid_endpoints
        or any(
            not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None
            for name in paid_endpoints
        )
    ):
        raise ValueError("paid_endpoints 必须声明至少一个非秘密连接别名")
    if pricing_method not in {"full_input_peak_v1", "observed_cache_v1"}:
        raise ValueError("不支持的冻结计价方法")
    if pricing_method == "observed_cache_v1" and cache_read_rate > input_rate:
        raise ValueError("缓存读取费率不能高于输入费率")
    usage, duplicates = _unique_usage(records)
    paid = [row for row in usage if row.endpoint in paid_endpoints]
    unpriced = [row for row in usage if row.endpoint not in paid_endpoints]
    input_tokens = sum(row.input_tokens for row in paid if row.input_tokens is not None)
    output_tokens = sum(row.output_tokens for row in paid if row.output_tokens is not None)
    estimate = (
        Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    ) / 1_000_000
    cache_states = (
        [_observed_cache(row) for row in paid] if pricing_method == "observed_cache_v1" else []
    )
    cache_read_tokens = sum(read for status, read in cache_states if status == "complete")
    estimate -= Decimal(cache_read_tokens) * (input_rate - cache_read_rate) / 1_000_000
    known = float(estimate)
    if not math.isfinite(known):
        raise ValueError("用量估价超出可报告的有限金额范围")
    incomplete = [
        row
        for index, row in enumerate(paid)
        if not row.complete or cache_states and cache_states[index][0] == "invalid"
    ]
    missing = (
        sum(row.missing_calls for row in paid if row.missing_calls is not None)
        if all(row.missing_calls is not None for row in paid)
        else None
    )
    result = {
        "currency": "CNY",
        "known_estimate_cny": known,
        "usage_complete": not incomplete,
        "incomplete_paid_records": len(incomplete),
        "missing_usage_calls": missing,
        "paid_records": len(paid),
        "unique_records": len(usage),
        "duplicate_records": duplicates,
        "reported_paid_input_tokens": input_tokens,
        "reported_paid_output_tokens": output_tokens,
        "paid_model_calls": sum(row.model_calls or 0 for row in paid)
        if all(row.model_calls is not None for row in paid)
        else None,
        "unpriced_records": len(unpriced),
        "unpriced_endpoints": sorted({row.endpoint for row in unpriced}),
        "local_cost_cny": None,
        "total_bill_cny": None,
        "paid_endpoints": sorted(set(paid_endpoints)),
        "input_cny_per_million": float(input_rate),
        "output_cny_per_million": float(output_rate),
        "pricing_method": pricing_method,
        "cache_read_cny_per_million": float(cache_read_rate)
        if pricing_method == "observed_cache_v1"
        else None,
        "cache_creation_cny_per_million": None,
        "reported_paid_cache_read_tokens": cache_read_tokens,
        "cache_unavailable_records": sum(status == "unavailable" for status, _ in cache_states),
        "cache_invalid_records": sum(status == "invalid" for status, _ in cache_states),
        "cache_discount_applied": cache_read_tokens > 0,
        "scope": "reported paid usage only; zero observations do not establish a zero bill",
    }
    return result, estimate


def estimate_paid_usage(
    records: Iterable[Record],
    *,
    paid_endpoints: tuple[str, ...] = ("remote",),
    input_cny_per_million: Rate = 2,
    output_cny_per_million: Rate = 8,
    pricing_method: str = "full_input_peak_v1",
    cache_read_cny_per_million: Rate = Decimal("0.04"),
) -> dict[str, Any]:
    """忽略缓存优惠，估计已知付费用量；本地连接与供应商总账单保持未知。"""

    result, _ = _estimate(
        records,
        paid_endpoints,
        _amount(input_cny_per_million, "input_cny_per_million"),
        _amount(output_cny_per_million, "output_cny_per_million"),
        pricing_method,
        _amount(cache_read_cny_per_million, "cache_read_cny_per_million"),
    )
    return result


def budget_reason(
    records: Iterable[Record],
    prior_records: Iterable[Record] = (),
    *,
    limit_cny: Rate,
    stop_fraction: Rate = 0.8,
    paid_endpoints: tuple[str, ...] = ("remote",),
    input_cny_per_million: Rate = 2,
    output_cny_per_million: Rate = 8,
    pricing_method: str = "full_input_peak_v1",
    cache_read_cny_per_million: Rate = Decimal("0.04"),
) -> str | None:
    """在任务派发前使用跨阶段记录；不取消或承诺在途请求的人民币硬上限。"""

    limit = _amount(limit_cny, "limit_cny")
    fraction = _amount(stop_fraction, "stop_fraction", positive=True)
    if fraction > 1:
        raise ValueError("stop_fraction 不能大于 1")
    result, estimate = _estimate(
        [*prior_records, *records],
        paid_endpoints,
        _amount(input_cny_per_million, "input_cny_per_million"),
        _amount(output_cny_per_million, "output_cny_per_million"),
        pricing_method,
        _amount(cache_read_cny_per_million, "cache_read_cny_per_million"),
    )
    if not result["usage_complete"]:
        return "paid_usage_incomplete"
    if estimate >= limit * fraction:
        return "paid_estimate_stop_fraction_reached"
    return None
