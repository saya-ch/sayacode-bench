"""先声明适用范围再分层抽样；公开冻结名单不包含答案、断言或绝对路径。"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Collection
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .sources import TaskRecord


@dataclass(frozen=True)
class Exclusion:
    benchmark: str
    task_id: str
    reason: str


@dataclass(frozen=True)
class SelectionManifest:
    seed: str
    dev: tuple[TaskRecord, ...]
    holdout: tuple[TaskRecord, ...]
    eligible_count: int
    exclusions: tuple[Exclusion, ...]
    rules: dict[str, Any]
    catalog_sha256: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "seed": self.seed,
            "catalog_sha256": self.catalog_sha256,
            "rules": self.rules,
            "eligible_count": self.eligible_count,
            "exclusions": [asdict(item) for item in self.exclusions],
            "dev": [item.public_dict() for item in self.dev],
            "holdout": [item.public_dict() for item in self.holdout],
            "interpretation": "固定公开基准子集；不代表完整榜单；调优只允许使用 dev",
        }


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}\0{value}".encode()).hexdigest()


def _exclusion(
    task: TaskRecord,
    max_memory_mb: int,
    languages: tuple[str, ...] | None,
    categories: tuple[str, ...] | None,
    max_agent_timeout_sec: float | None,
) -> str | None:
    environment = task.environment
    if task.has_custom_compose:
        return "custom_compose_not_supported_by_local_network_protocol"
    if environment.get("os", "linux") != "linux":
        return "only_linux_container_runtime_available"
    if environment.get("gpus", 0) != 0:
        return "gpu_not_available"
    memory = environment.get("memory_mb")
    if not isinstance(memory, (int, float)) or isinstance(memory, bool) or memory <= 0:
        return "missing_or_invalid_official_memory_budget"
    if memory > max_memory_mb:
        return "official_memory_exceeds_declared_host_budget"
    if not environment.get("docker_image"):
        return "prebuilt_image_required_for_this_study"
    if languages is not None and task.language not in languages:
        return "outside_predeclared_language_scope"
    if categories is not None and task.category not in categories:
        return "outside_predeclared_category_scope"
    if max_agent_timeout_sec is not None:
        timeout = task.agent.get("timeout_sec")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            return "missing_or_invalid_official_agent_timeout"
        if timeout > max_agent_timeout_sec:
            return "official_agent_timeout_exceeds_study_scope"
    return None


def select_tasks(
    catalog: list[TaskRecord],
    *,
    dev_count: int,
    holdout_count: int,
    seed: str,
    max_memory_mb: int = 4096,
    preferred_languages: tuple[str, ...] = ("python",),
    languages: tuple[str, ...] | None = None,
    excluded_leakage_groups: Collection[str] = (),
    categories: tuple[str, ...] | None = None,
    max_agent_timeout_sec: float | None = None,
) -> SelectionManifest:
    """按仓库（SWE）或类别（终端）轮转抽样，同一修复组不跨开发/验收集。"""

    if dev_count < 1 or holdout_count < 1 or not seed or max_memory_mb < 1:
        raise ValueError("开发和验收数量、种子与资源预算必须有效")
    if categories is not None and (
        not isinstance(categories, tuple)
        or not categories
        or any(not isinstance(category, str) or not category.strip() for category in categories)
    ):
        raise ValueError("categories 必须是非空类别名的非空 tuple，或为 None")
    if max_agent_timeout_sec is not None and (
        type(max_agent_timeout_sec) not in (int, float)
        or not math.isfinite(max_agent_timeout_sec)
        or max_agent_timeout_sec <= 0
    ):
        raise ValueError("max_agent_timeout_sec 必须是正有限秒数，或为 None")
    if isinstance(excluded_leakage_groups, str) or any(
        not isinstance(group, str) or not group.strip() for group in excluded_leakage_groups
    ):
        raise ValueError("excluded_leakage_groups 必须是非空组名的集合")
    excluded_groups = set(excluded_leakage_groups)
    matched_groups = set()
    keys = [(task.benchmark, task.task_id) for task in catalog]
    if len(keys) != len(set(keys)):
        raise ValueError("catalog 包含重复任务标识")
    catalog = sorted(catalog, key=lambda task: (task.benchmark, task.task_id))
    exclusions = []
    grouped: dict[str, list[TaskRecord]] = defaultdict(list)
    for task in catalog:
        # 原始 fix 组已经包含仓库；带基准前缀可进一步限定跨基准同名组。
        matches = excluded_groups.intersection(
            {task.leakage_group, f"{task.benchmark}:{task.leakage_group}"}
        )
        if matches:
            matched_groups.update(matches)
            exclusions.append(Exclusion(task.benchmark, task.task_id, "calibration_group"))
            continue
        reason = _exclusion(task, max_memory_mb, languages, categories, max_agent_timeout_sec)
        if reason:
            exclusions.append(Exclusion(task.benchmark, task.task_id, reason))
        else:
            grouped[f"{task.benchmark}:{task.leakage_group}"].append(task)
    # 同修复的版本只选一个；所有未选版本也公开记录，避免意外跨集泄漏。
    eligible = []
    for group in grouped.values():
        variants = sorted(group, key=lambda task: _rank(seed, task.task_id))
        eligible.append(variants[0])
        for task in variants[1:]:
            exclusions.append(
                Exclusion(task.benchmark, task.task_id, "duplicate_fixing_commit_group")
            )
    if len(eligible) < dev_count + holdout_count:
        raise ValueError(
            f"适用任务只有 {len(eligible)} 个，不足以抽取 {dev_count + holdout_count} 个"
        )

    strata: dict[str, list[TaskRecord]] = defaultdict(list)
    for task in eligible:
        label = task.repository if task.benchmark == "swe-bench-pro-v2" else task.category
        strata[f"{task.benchmark}:{label}"].append(task)
    for values in strata.values():
        values.sort(key=lambda task: _rank(seed, f"{task.benchmark}:{task.leakage_group}"))

    def stratum_rank(key: str) -> tuple[int, str]:
        preferred = any(task.language in preferred_languages for task in strata[key])
        return (0 if preferred else 1, _rank(seed, key))

    ordered_keys = sorted(strata, key=stratum_rank)

    def take(count: int) -> tuple[TaskRecord, ...]:
        selected: list[TaskRecord] = []
        while len(selected) < count:
            for key in ordered_keys:
                if strata[key] and len(selected) < count:
                    selected.append(strata[key].pop())
        return tuple(selected)

    # 两集合分别轮转分层；按总体顺序机械交错会在分母整除时导致仓库完全分离。
    dev = take(dev_count)
    holdout = take(holdout_count)
    return SelectionManifest(
        seed=seed,
        dev=dev,
        holdout=holdout,
        eligible_count=len(eligible),
        exclusions=tuple(sorted(exclusions, key=lambda item: (item.benchmark, item.task_id))),
        rules={
            "max_memory_mb": max_memory_mb,
            "concurrency": 1,
            "resources": "preserve official per-task environment/agent/verifier configuration",
            "topology": "single-container tasks only; custom Compose excluded before model trials",
            "languages": languages,
            "categories": tuple(sorted(set(categories))) if categories is not None else None,
            "max_agent_timeout_sec": max_agent_timeout_sec,
            "preferred_languages": preferred_languages,
            "excluded_leakage_groups": sorted(excluded_groups),
            "excluded_group_matching": "exact leakage_group or benchmark:leakage_group",
            "unmatched_excluded_leakage_groups": sorted(excluded_groups - matched_groups),
            "strata": "repository for SWE; category for Terminal-Bench",
            "ordering": "sha256 seeded group order; independent round-robin coverage for dev then holdout",
            "leakage_guard": "one variant per repository/fixing commit; no cross-split overlap",
            "exclusion_timing": "before any model result; no score-dependent replacement",
        },
        catalog_sha256=_json_hash([task.public_dict() for task in catalog]),
    )


def write_manifest(manifest: SelectionManifest, destination: Path) -> str:
    """冻结名单只能新建；已有研究不可无声改写。"""

    payload = (
        json.dumps(manifest.public_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
    return hashlib.sha256(payload.encode()).hexdigest()
