"""任务版本、真实探针和评测实现的前置证据门禁。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .artifacts import file_sha256

TASK_IDENTITIES = ("instruction_sha256", "config_sha256", "task_tree_sha256")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _qualified_trials(row: dict[str, Any], task_id: str) -> None:
    """正式冻结重查固定三加一及独立原生证据，不能只信汇总 passed。"""
    oracle = row.get("oracle_trials")
    nop = row.get("nop")
    if (
        type(row.get("oracle_repeats")) is not int
        or row["oracle_repeats"] != 3
        or not isinstance(oracle, list)
        or len(oracle) != 3
        or not isinstance(nop, dict)
        or row.get("oracle") != oracle[0]
    ):
        raise ValueError("正式评分门禁必须包含固定三次 oracle 和一次 nop 原生结果")
    requests, native_results = set(), set()
    runtimes = []
    for trial, agent, repeat, reward in [
        *((trial, "oracle", index, 1) for index, trial in enumerate(oracle, 1)),
        (nop, "nop", 1, 0),
    ]:
        if (
            not isinstance(trial, dict)
            or trial.get("task_id") != task_id
            or trial.get("configuration") != agent
            or type(trial.get("repeat")) is not int
            or trial["repeat"] != repeat
            or trial.get("record_complete") is not True
            or trial.get("status") != "completed"
            or trial.get("verified") is not True
            or trial.get("success") is not (reward == 1)
            or type(trial.get("original_reward")) not in (int, float)
            or trial["original_reward"] != reward
        ):
            raise ValueError("固定 oracle/nop 任务身份、状态或官方评分未确认")
        runtime = trial.get("runtime_identity")
        if (
            not isinstance(runtime, dict)
            or runtime.get("available") is not True
            or any(
                not isinstance(runtime.get(key), str) or not runtime[key]
                for key in ("image_id", "architecture", "os")
            )
            or not isinstance(runtime.get("requested"), dict)
            or not isinstance(runtime.get("docker_limits"), dict)
        ):
            raise ValueError("固定 oracle/nop 缺少原生镜像、平台或资源证据")
        runtimes.append(
            {
                key: runtime[key]
                for key in ("image_id", "architecture", "os", "requested", "docker_limits")
            }
        )
        request = trial.get("request_sha256")
        native = trial.get("raw_trial_result")
        observation = trial.get("runtime")
        if (
            not isinstance(request, str)
            or not _SHA256.fullmatch(request)
            or not isinstance(native, dict)
            or not isinstance(native.get("sha256"), str)
            or not _SHA256.fullmatch(native["sha256"])
            or not isinstance(observation, dict)
            or not isinstance(observation.get("sha256"), str)
            or not _SHA256.fullmatch(observation["sha256"])
        ):
            raise ValueError("固定 oracle/nop 缺少原生结果与运行时工件哈希")
        requests.add(request)
        native_results.add(native["sha256"])
    if len(requests) != 4 or len(native_results) != 4:
        raise ValueError("三次 oracle 和一次 nop 必须来自四次独立原生试验")
    if any(runtime != runtimes[0] for runtime in runtimes[1:]):
        raise ValueError("固定 oracle/nop 的实际镜像、平台或资源不一致")


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
    if sanity.get("complete") is not True or sanity.get("passed") is not True:
        raise ValueError("评分门禁未完成")
    checked = {row["task_id"]: row for row in sanity["tasks"]}
    for task in tasks:
        row = checked.get(task["task_id"], {})
        if row.get("passed") is not True or any(
            row.get(key) != task.get(key) for key in TASK_IDENTITIES
        ):
            raise ValueError("任务身份或参考解/空解门禁未确认")
        _qualified_trials(row, task["task_id"])
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
