"""只读核验官方声明、Docker 与 cgroup 资源证据；未知不等于一致。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Any


class _Missing(Exception):
    pass


def _object(value: Any) -> Mapping[str, Any]:
    if value is None:
        raise _Missing
    if not isinstance(value, Mapping):
        raise ValueError("invalid_resource_object")
    return value


def _value(value: Mapping[str, Any], key: str) -> Any:
    if key not in value or value[key] is None:
        raise _Missing
    return value[key]


def _integer(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("invalid_resource_integer")
    return value


def _cpu(value: Any) -> Fraction:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("invalid_cpu_budget")
    return Fraction(str(value))


def _cgroup_integer(value: Any, *, minimum: int = 0) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError("unconfirmed_or_unlimited_cgroup_budget")
    return _integer(int(value), minimum=minimum)


def _resources(
    runtime: Any, task_environment: Mapping[str, Any] | None
) -> tuple[bool | None, dict[str, Any] | None]:
    try:
        source = _object(runtime)
        if source.get("available") is not True:
            raise _Missing
        requested = _object(_value(source, "requested"))
        docker = _object(_value(source, "docker_limits"))
        cgroup = _object(_value(source, "cgroup_v2"))
        declared = _object(task_environment)
        cpus = _cpu(_value(requested, "cpus"))
        memory = _integer(_value(requested, "memory_mb"), minimum=1) * 1024**2
        if (
            cpus != _cpu(_value(declared, "cpus"))
            or memory != _integer(_value(declared, "memory_mb"), minimum=1) * 1024**2
        ):
            raise ValueError("requested_resources_differ_from_task")
        nanos = _integer(_value(docker, "NanoCpus"))
        period = _integer(_value(docker, "CpuPeriod"))
        quota = _integer(_value(docker, "CpuQuota"))
        if nanos:
            if Fraction(nanos, 10**9) != cpus or (
                quota and (not period or Fraction(quota, period) != cpus)
            ):
                raise ValueError("docker_cpu_differs_from_task")
        elif not quota or not period or Fraction(quota, period) != cpus:
            raise ValueError("docker_cpu_unlimited_or_mismatched")
        cpu_max = _value(cgroup, "cpu.max")
        if not isinstance(cpu_max, str) or len(parts := cpu_max.split()) != 2:
            raise ValueError("invalid_cgroup_cpu")
        cg_quota = _cgroup_integer(parts[0], minimum=1)
        cg_period = _cgroup_integer(parts[1], minimum=1)
        if Fraction(cg_quota, cg_period) != cpus:
            raise ValueError("cgroup_cpu_differs_from_task")
        docker_memory = _integer(_value(docker, "Memory"), minimum=1)
        docker_swap_total = _integer(_value(docker, "MemorySwap"), minimum=1)
        cg_memory = _cgroup_integer(_value(cgroup, "memory.max"), minimum=1)
        cg_swap = _cgroup_integer(_value(cgroup, "memory.swap.max"))
        if docker_memory != memory or cg_memory != memory or docker_swap_total - memory != cg_swap:
            raise ValueError("docker_cgroup_memory_or_swap_mismatch")
        storage = _value(source, "storage_hard_limit_supported")
        if type(storage) is not bool:
            raise ValueError("unknown_storage_limit_scope")
        return True, {
            "requested": {
                key: requested.get(key)
                for key in ("cpus", "memory_mb", "storage_mb", "docker_image")
            },
            "docker_limits": {
                key: docker[key]
                for key in ("NanoCpus", "CpuPeriod", "CpuQuota", "Memory", "MemorySwap")
            },
            "cgroup_v2": {
                "cpu.max": (cg_quota, cg_period),
                "memory.max": cg_memory,
                "memory.swap.max": cg_swap,
            },
            "storage_hard_limit_supported": storage,
        }
    except _Missing:
        return None, None
    except (ValueError, TypeError, OverflowError):
        return False, None


def resource_status(runtime: Any, task_environment: Mapping[str, Any] | None = None) -> bool | None:
    """True 为已核实；False 为明确冲突或无限额；None 为证据缺失。"""
    return _resources(runtime, task_environment)[0]


def compare_runtimes(
    left: Any, right: Any, task_environment: Mapping[str, Any] | None = None
) -> dict[str, bool | None]:
    """逐项比较实际身份；资源还须各自符合任务，两个同样无限额不能算相同。"""
    result: dict[str, bool | None] = {
        "same_image": None,
        "same_platform": None,
        "same_resources": None,
    }
    a, b = left if isinstance(left, Mapping) else {}, right if isinstance(right, Mapping) else {}
    if a.get("available") is True and b.get("available") is True:
        if all(isinstance(value.get("image_id"), str) and value["image_id"] for value in (a, b)):
            result["same_image"] = a["image_id"] == b["image_id"]
        if all(
            isinstance(value.get(key), str) and value[key]
            for value in (a, b)
            for key in ("architecture", "os")
        ):
            result["same_platform"] = all(a[key] == b[key] for key in ("architecture", "os"))
    first, first_facts = _resources(left, task_environment)
    second, second_facts = _resources(right, task_environment)
    if first is False or second is False:
        result["same_resources"] = False
    elif first is True and second is True:
        result["same_resources"] = first_facts == second_facts
    return result


def runtime_record_issues(
    record: Mapping[str, Any], task: Mapping[str, Any], qualified: Any, *, replay: bool
) -> list[str]:
    """不信任保存的比较布尔值，从原始白名单事实重算源／重判／资格一致性。"""
    environment = task.get("environment")
    declared = environment if isinstance(environment, Mapping) else {}
    source = record.get("runtime_identity")
    pairs = [("source_qualification", source, qualified)]
    if replay:
        target = record.get("replay_runtime_identity")
        pairs.extend(
            (("replay_qualification", target, qualified), ("source_replay", source, target))
        )
    return [
        f"{label}_{field}_{'mismatch' if value is False else 'unconfirmed'}"
        for label, left, right in pairs
        for field, value in compare_runtimes(left, right, declared).items()
        if value is not True
    ]
