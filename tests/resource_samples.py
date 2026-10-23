"""纯合成的完整资源观测，供离线回归使用，不代表真实容器证据。"""

from __future__ import annotations

from typing import Any

from sayacode_bench.artifacts import implementation_identity


def runtime_evidence(*, image_id: str = "sha256:" + "a" * 64) -> dict[str, Any]:
    return {
        "available": True,
        "image_id": image_id,
        "architecture": "amd64",
        "os": "linux",
        "requested": {"cpus": 1, "memory_mb": 4096},
        "docker_limits": {
            "NanoCpus": 1_000_000_000,
            "CpuPeriod": 0,
            "CpuQuota": 0,
            "Memory": 4294967296,
            "MemorySwap": 8589934592,
        },
        "cgroup_v2": {
            "cpu.max": "100000 100000",
            "memory.max": "4294967296",
            "memory.swap.max": "4294967296",
        },
        "storage_hard_limit_supported": False,
    }


def complete_resource_fixture(manifest: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """给纯统计／签收用例补齐合成资源证据，不以省略正式策略来放行。"""
    manifest["runtime_evidence_required"] = True
    manifest.setdefault("implementation", implementation_identity())
    manifest.setdefault("benchmark", "swe-bench-pro-v2")
    manifest["qualified_runtime_identities"] = {
        task["task_id"]: runtime_evidence() for task in manifest["tasks"]
    }
    for task in manifest["tasks"]:
        task.setdefault("environment", {"cpus": 1, "memory_mb": 4096})
    for record in records:
        record.setdefault("runtime_identity", runtime_evidence())
        record.setdefault("replay_runtime_identity", runtime_evidence())
