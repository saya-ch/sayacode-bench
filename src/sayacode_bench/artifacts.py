"""固定研究文件身份并保存可审计的中止记录。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_identity() -> dict[str, str]:
    """冻结评测实现本身，不能在半批次内更换适配器或统计规则。"""
    package = Path(__file__).parent
    files = {path.name: file_sha256(path) for path in sorted(package.glob("*.py"))}
    root = package.parent.parent
    for name in ("pyproject.toml", "uv.lock"):
        files[name] = file_sha256(root / name)
    return files


def report_manifest(manifest: dict[str, Any], results_root: Path) -> dict[str, Any]:
    """重汇总也必须继承结果目录的中止和失效事实。"""
    issues = list(manifest.get("validity_issues", []))
    for name, reason in (
        ("abort.json", "experiment_aborted"),
        ("invalid.json", "experiment_invalid"),
    ):
        if (results_root / name).exists():
            issues.append(reason)
    return {**manifest, "validity_issues": sorted(set(issues))}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("研究文件必须为 JSON 对象")
    return value


def write_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    """最终清单拒绝覆盖；派生进度用原子替换写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(f"已冻结的文件不能覆盖：{path.name}")
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)


def record_stop(output: Path, reason: str, *, details: dict[str, Any] | None = None) -> None:
    write_json(
        output / "abort.json",
        {"at": datetime.now(UTC).isoformat(), "reason": reason, "details": details or {}},
        exclusive=True,
    )


def fatal_stop_reason(records: Sequence[Mapping[str, Any]]) -> str | None:
    """重查已声明的外部故障止损；末项和历史窗口也不能在离线报告时消失。"""
    recent_connection_failures: list[bool] = []
    for record in records:
        codes = record.get("terminal_http_statuses", [])
        codes = codes if isinstance(codes, (list, tuple)) else []
        if record.get("terminal_http_status") in {401, 402, 403, 429} or any(
            type(code) is int and code in {401, 402, 403, 429} for code in codes
        ):
            return "model_service_limit"
        if record.get("status") in {"infrastructure_error", "result_unknown"}:
            return "trial_infrastructure_failure"
        if record.get("status") == "completed" and record.get("success") is None:
            return "verification_unconfirmed"
        recent_connection_failures.append(record.get("failure_category") == "model_connection")
        recent_connection_failures = recent_connection_failures[-5:]
        if sum(recent_connection_failures) >= 2:
            return "unstable_model_connection"
    return None


def check_budget(records: list[dict[str, Any]], *, reported_token_limit: int) -> str | None:
    """按已报告用量停止新派发，不能把这个阈值说成完整计费上限。"""
    fatal = fatal_stop_reason(records)
    if fatal:
        return fatal
    tokens = sum(
        sum(
            value
            for field in ("input_tokens", "output_tokens")
            if type(value := row.get(field)) is int and value >= 0
        )
        for row in records
    )
    return "reported_token_threshold" if tokens >= reported_token_limit else None
