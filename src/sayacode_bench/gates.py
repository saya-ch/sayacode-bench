"""任务版本、真实探针和评测实现的前置证据门禁。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import file_sha256

TASK_IDENTITIES = ("instruction_sha256", "config_sha256", "task_tree_sha256")


def validate_preflight(
    sanity: dict[str, Any],
    probe: dict[str, Any],
    *,
    benchmark: str,
    revision: str,
    tasks: list[dict[str, Any]],
) -> None:
    if sanity.get("benchmark") != benchmark or sanity.get("revision") != revision:
        raise ValueError("评分门禁属于另一数据版本")
    if sanity.get("complete") is not True:
        raise ValueError("评分门禁未完成")
    checked = {row["task_id"]: row for row in sanity["tasks"]}
    for task in tasks:
        row = checked.get(task["task_id"], {})
        if row.get("passed") is not True or any(
            row.get(key) != task.get(key) for key in TASK_IDENTITIES
        ):
            raise ValueError("任务身份或参考解/空解门禁未确认")
    network_file = Path(__file__).with_name("network.py")
    if (
        probe.get("passed") is not True
        or probe.get("cleanup_confirmed") is not True
        or probe.get("source_sha256", {}).get("network.py") != file_sha256(network_file)
    ):
        raise ValueError("真实网络探针未通过或实现身份已变化")


def validate_directories(
    output: Path,
    cache: Path,
    wheel: Path,
    requirements: Path,
    private_home: Path,
) -> None:
    output, private_home = output.resolve(), private_home.resolve()
    if private_home.is_relative_to(output):
        raise ValueError("私有连接目录不能位于结果归档目录中")
    package_root = Path(__file__).resolve().parent.parent.parent
    for protected in (
        cache.resolve(),
        wheel.resolve().parent,
        requirements.resolve().parent,
        package_root,
    ):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("结果目录必须与源缓存、生产包和评测源码隔离")
