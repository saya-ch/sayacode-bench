"""固定安装预检的 Actions 存储守卫；只读 GET，不删除、不改变账单设置。"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, write_json

PUBLIC = "saya-ch/sayacode-bench"
PRIVATE = "saya-ch/sayacode-bench-runs"
PRIVATE_ID = 1429748203
MAX_PARALLEL = 4
MAX_FALLBACK_BYTES = 10_000_000
PRIVATE_BASELINE_BYTES = 125_000_000
INFLIGHT_RESERVE_BYTES = 50_000_000
CEILING_BYTES = 330_000_000


class StorageUnconfirmed(ValueError):
    """只保存固定错误说明，避免把 gh 原响应或凭据写进摘要。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StorageUnconfirmed(message)


def _get(endpoint: str, *, paginate: bool = False) -> Any:
    arguments = ["gh", "api", endpoint, "--hostname", "github.com", "--method", "GET"]
    if paginate:
        arguments.extend(["--paginate", "--slurp"])
    try:
        result = subprocess.run(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        _require(result.returncode == 0, "gh GET 未成功；存储状态未确认")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, UnicodeError):
        raise StorageUnconfirmed("gh GET 未返回完整有效 JSON；存储状态未确认") from None


def _inventory(repository: str) -> dict[str, Any]:
    pages = _get(f"repos/{repository}/actions/artifacts?per_page=100", paginate=True)
    _require(isinstance(pages, list) and bool(pages), "artifact 分页列表缺失")
    total: int | None = None
    seen: set[int] = set()
    active: list[dict[str, int]] = []
    for index, page in enumerate(pages):
        _require(isinstance(page, dict), "artifact 分页对象无效")
        count, artifacts = page.get("total_count"), page.get("artifacts")
        _require(
            type(count) is int and count >= 0 and isinstance(artifacts, list),
            "artifact 分页计数无效",
        )
        if total is None:
            total = count
        _require(count == total, "artifact 分页期间总数改变，无法确认完整快照")
        _require(
            len(artifacts) <= 100 and (index == len(pages) - 1 or len(artifacts) == 100),
            "artifact 分页长度不完整",
        )
        for artifact in artifacts:
            _require(isinstance(artifact, dict), "artifact 项无效")
            identity, size, expired = (
                artifact.get("id"),
                artifact.get("size_in_bytes"),
                artifact.get("expired"),
            )
            _require(
                type(identity) is int and identity > 0 and identity not in seen,
                "artifact ID 缺失或重复",
            )
            _require(
                type(size) is int and size >= 0 and type(expired) is bool,
                "artifact 大小或过期状态无效",
            )
            seen.add(identity)
            if not expired:
                active.append({"id": identity, "size_in_bytes": size})
    _require(total == len(seen), "artifact 分页未完整覆盖 total_count")
    _require(len(pages) == max(1, (len(seen) + 99) // 100), "artifact 分页数量不符")
    return {
        "repository": repository,
        "pages": len(pages),
        "total_count": total,
        "active_count": len(active),
        "actual_bytes": sum(item["size_in_bytes"] for item in active),
        "active_artifacts": active,
    }


def _guard() -> dict[str, Any]:
    repository = _get(f"repos/{PRIVATE}")
    _require(
        isinstance(repository, dict)
        and type(repository.get("id")) is int
        and repository["id"] == PRIVATE_ID
        and repository.get("full_name") == PRIVATE
        and repository.get("private") is True
        and repository.get("visibility") == "private",
        "固定私有仓库身份或私有性未确认",
    )
    public, private = _inventory(PUBLIC), _inventory(PRIVATE)
    fallback_reserve = MAX_PARALLEL * MAX_FALLBACK_BYTES
    private_guard = max(PRIVATE_BASELINE_BYTES, private["actual_bytes"] + fallback_reserve)
    projected = public["actual_bytes"] + private_guard + INFLIGHT_RESERVE_BYTES
    return {
        "private_repository_id": PRIVATE_ID,
        "public_actual_bytes": public["actual_bytes"],
        "private_actual_bytes": private["actual_bytes"],
        "max_parallel": MAX_PARALLEL,
        "max_raw_fallback_bytes": MAX_FALLBACK_BYTES,
        "concurrent_raw_fallback_reserve_bytes": fallback_reserve,
        "private_baseline_bytes": PRIVATE_BASELINE_BYTES,
        "private_guard_bytes": private_guard,
        "inflight_reserve_bytes": INFLIGHT_RESERVE_BYTES,
        "projected_bytes": projected,
        "ceiling_bytes": CEILING_BYTES,
        "inventories": [public, private],
    }


def check_storage(operation: str, archive: Path | None = None) -> dict[str, Any]:
    """返回派发或 fallback 的准入快照；成功也不表示上传已经发生。"""
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": operation,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "status": "retention_unconfirmed",
        "passed": False,
        "fallback_ready": False,
        "retention_confirmed": False,
        "deletion_performed": False,
        "billing_settings_changed": False,
        "scope": "只读 Actions artifact 快照门禁；不验证上传，不取代免费账单设置。",
    }
    try:
        _require(operation in {"reserve", "fallback"}, "不支持的操作")
        if operation == "fallback":
            if archive is None:
                raise StorageUnconfirmed("fallback 缺少归档文件")
            _require(
                archive.is_file() and not archive.is_symlink(),
                "fallback 必须是已生成的普通归档文件",
            )
            size = archive.stat().st_size
            report["archive"] = {"path": str(archive.resolve()), "size_in_bytes": size}
            _require(
                0 < size <= MAX_FALLBACK_BYTES, "raw fallback 归档须非空且不超过 10,000,000 字节"
            )
            report["archive"]["sha256"] = file_sha256(archive)
        else:
            _require(archive is None, "reserve 不接受归档输入")
        report.update(_guard())
        _require(
            report["projected_bytes"] <= CEILING_BYTES,
            "四项 fallback 并发预留后超过 330,000,000 字节门禁",
        )
        # 网络读取期间归档也必须保持为同一完整字节身份。
        if archive is not None:
            _require(
                archive.stat().st_size == report["archive"]["size_in_bytes"]
                and file_sha256(archive) == report["archive"]["sha256"],
                "fallback 归档在检查期间改变",
            )
        report.update(status="passed", passed=True, fallback_ready=operation == "fallback")
    except (StorageUnconfirmed, OSError) as error:
        report["reason"] = (
            str(error)
            if isinstance(error, StorageUnconfirmed)
            else "本地归档读取失败；原件保全尚未确认"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    reserve = commands.add_parser("reserve")
    reserve.add_argument("--output", type=Path, required=True)
    fallback = commands.add_parser("fallback")
    fallback.add_argument("--archive", type=Path, required=True)
    fallback.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = check_storage(args.operation, getattr(args, "archive", None))
    try:
        write_json(args.output, report, exclusive=True)
    except OSError:
        # 既有诊断也不覆盖；退出码阻止误用旧的 passed 文件。
        print(
            json.dumps(
                {
                    "status": "retention_unconfirmed",
                    "passed": False,
                    "fallback_ready": False,
                    "output_written": False,
                    "reason": "诊断文件无法独占写入；已有文件保持原样",
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "operation",
                    "status",
                    "passed",
                    "fallback_ready",
                    "retention_confirmed",
                )
            }
            | {"output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
