"""封存开发选择，并在最终阶段核查源码身份与任务泄漏。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis import select_development_candidate
from .artifacts import file_sha256, read_json, write_json

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} 必须是完整 SHA256")
    return value


def _records(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("逐次记录必须为 JSON 对象")
        if row.get("record_complete") is not True:
            raise ValueError("开发试验未收尾，不能锁定候选")
        rows.append(row)
    return rows


def _task_evidence(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("需要非空任务清单")
    result = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("任务必须是对象")
        identifier, group = task.get("task_id"), task.get("leakage_group")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(group, str)
            or not group
        ):
            raise ValueError("每道任务都需要 task_id 和 leakage_group")
        result.append({"task_id": identifier, "leakage_group": group})
    if len({task["task_id"] for task in result}) != len(result):
        raise ValueError("任务 ID 重复")
    if len({task["leakage_group"] for task in result}) != len(result):
        raise ValueError("同一阶段存在重复修复组，不能作为独立任务计数")
    return result


def _artifacts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = manifest.get("artifacts")
    if not isinstance(value, dict) or not isinstance(value.get("variants"), dict):
        raise ValueError("清单缺少已冻结工件身份")
    return {
        "product_wheel": _digest(value.get("product_wheel"), "product_wheel"),
        "requirements": _digest(value.get("requirements"), "requirements"),
        "variants": {
            label: _digest(digest, f"variant:{label}")
            for label, digest in value["variants"].items()
        },
    }


def _verify_variant_files(
    paths: Mapping[str, Path], expected: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    if set(paths) != set(expected):
        raise ValueError("配置文件与冻结配置标签不一致")
    result = {}
    for label, path in paths.items():
        resolved = path.resolve(strict=True)
        actual = file_sha256(resolved)
        if actual != expected[label]:
            raise ValueError(f"配置内容已变化：{label}")
        result[label] = {"path": str(resolved), "sha256": actual}
    return result


def _financially_confirmed(manifest: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if manifest.get("paid_budget") is None:
        return
    # 函数内导入避免 study 的最终候选复核形成模块循环。
    from .study import paid_budget_report

    try:
        report = paid_budget_report(manifest, rows)
        confirmed = (
            report is not None
            and report.get("evidence_valid") is True
            and report.get("usage_complete") is True
        )
    except (OSError, ValueError, KeyError, TypeError):
        confirmed = False
    if not confirmed:
        raise ValueError("开发费用证据无效或用量未知，不能签收候选")


def lock_candidate(
    dev_manifest_path: Path,
    records_path: Path,
    variant_paths: Mapping[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    """仅对完整开发结果签收选择；已有签收单拒绝覆盖。"""
    if output_path.exists():
        raise FileExistsError("候选签收单已经存在，不能覆盖")
    dev_manifest_path = dev_manifest_path.resolve(strict=True)
    records_path = records_path.resolve(strict=True)
    manifest_hash, records_hash = file_sha256(dev_manifest_path), file_sha256(records_path)
    manifest = read_json(dev_manifest_path)
    if manifest.get("phase") != "dev" or manifest.get("frozen") is not True:
        raise ValueError("只能锁定已冻结的 dev 阶段")
    if any((records_path.parent / name).exists() for name in ("abort.json", "invalid.json")):
        raise ValueError("开发批次已中止或失效，不能锁定候选")
    rows = _records(records_path)
    _financially_confirmed(manifest, rows)
    selection = select_development_candidate(manifest, rows)
    if selection.get("status") != "selected" or selection.get("selected") is None:
        raise ValueError("开发结果缺失、未知或不可比较，不能锁定候选")
    tasks = _task_evidence(manifest)
    artifacts = _artifacts(manifest)
    if set(artifacts["variants"]) != set(manifest["configurations"]):
        raise ValueError("开发工件与配置标签不一致")
    variant_files = _verify_variant_files(variant_paths, artifacts["variants"])
    if file_sha256(dev_manifest_path) != manifest_hash or file_sha256(records_path) != records_hash:
        raise ValueError("封存期间开发输入变化")
    receipt = {
        "schema_version": 1,
        "locked_at": datetime.now(UTC).isoformat(),
        "baseline": manifest["baseline"],
        "selected": selection["selected"],
        "canonical_model": manifest["canonical_model"],
        "selection": selection,
        "dev_manifest": {"path": str(dev_manifest_path), "sha256": manifest_hash},
        "dev_records": {"path": str(records_path), "sha256": records_hash},
        "dev_tasks": tasks,
        "dev_task_ids": sorted(task["task_id"] for task in tasks),
        "dev_leakage_groups": sorted({task["leakage_group"] for task in tasks}),
        "artifacts": artifacts,
        "variant_files": variant_files,
    }
    write_json(output_path, receipt, exclusive=True)
    return receipt


def validate_candidate_receipt(
    receipt_path: Path,
    final_manifest: Mapping[str, Any],
    *,
    variant_paths: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """最终清单冻结前核对签收来源、配置身份和任务隔离。"""
    receipt_path = receipt_path.resolve(strict=True)
    receipt = read_json(receipt_path)
    if receipt.get("schema_version") != 1:
        raise ValueError("不支持的候选签收版本")
    sources = {}
    for field in ("dev_manifest", "dev_records"):
        identity = receipt.get(field)
        if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
            raise ValueError("候选签收来源缺失")
        path = Path(identity["path"]).resolve(strict=True)
        if file_sha256(path) != _digest(identity.get("sha256"), field):
            raise ValueError(f"候选来源已变化：{field}")
        sources[field] = path
    manifest = read_json(sources["dev_manifest"])
    if manifest.get("phase") != "dev" or manifest.get("frozen") is not True:
        raise ValueError("候选来源不是冻结开发集")
    if any(
        (sources["dev_records"].parent / name).exists() for name in ("abort.json", "invalid.json")
    ):
        raise ValueError("候选开发批次已中止或失效")
    rows = _records(sources["dev_records"])
    _financially_confirmed(manifest, rows)
    selection = select_development_candidate(manifest, rows)
    if selection.get("status") != "selected" or selection != receipt.get("selection"):
        raise ValueError("候选选择与冻结开发结果不一致")
    if (
        receipt.get("selected") != selection["selected"]
        or receipt.get("baseline") != manifest["baseline"]
    ):
        raise ValueError("候选签收标签被修改")
    if (
        receipt.get("canonical_model") != manifest["canonical_model"]
        or final_manifest.get("canonical_model") != manifest["canonical_model"]
    ):
        raise ValueError("最终模型与开发锁定不同")
    artifacts = _artifacts(manifest)
    if artifacts != receipt.get("artifacts"):
        raise ValueError("候选签收工件身份被修改")
    files = receipt.get("variant_files")
    if not isinstance(files, dict) or set(files) != set(artifacts["variants"]):
        raise ValueError("签收配置来源不完整")
    for label, digest in artifacts["variants"].items():
        identity = files[label]
        if (
            not isinstance(identity, dict)
            or identity.get("sha256") != digest
            or not isinstance(identity.get("path"), str)
        ):
            raise ValueError("签收配置来源身份被修改")
    final_artifacts = _artifacts(final_manifest)
    for field in ("product_wheel", "requirements"):
        if final_artifacts[field] != artifacts[field]:
            raise ValueError(f"最终 {field} 与开发阶段不一致")
    baseline, selected = receipt["baseline"], receipt["selected"]
    if selected == baseline:
        expected_labels = [baseline]
        if (
            final_manifest.get("phase") != "validation"
            or final_manifest.get("candidate") is not None
        ):
            raise ValueError("保留基线时只能执行 validation，不制造基线自比")
    else:
        expected_labels = [baseline, selected]
        if final_manifest.get("phase") != "holdout" or final_manifest.get("candidate") != selected:
            raise ValueError("最终 holdout 必须使用开发选中的唯一候选")
    if (
        final_manifest.get("baseline") != baseline
        or final_manifest.get("configurations") != expected_labels
    ):
        raise ValueError("最终配置标签或顺序与签收不一致")
    if set(final_artifacts["variants"]) != set(expected_labels):
        raise ValueError("最终工件配置不完整或有额外候选")
    for label in expected_labels:
        if final_artifacts["variants"][label] != artifacts["variants"][label]:
            raise ValueError(f"最终配置与开发不同：{label}")
    if variant_paths is None:
        variant_paths = {label: Path(files[label]["path"]) for label in expected_labels}
    _verify_variant_files(variant_paths, final_artifacts["variants"])
    dev_tasks = _task_evidence(manifest)
    if dev_tasks != receipt.get("dev_tasks"):
        raise ValueError("签收的开发任务证据被修改")
    task_ids = {task["task_id"] for task in dev_tasks}
    groups = {task["leakage_group"] for task in dev_tasks}
    if sorted(task_ids) != receipt.get("dev_task_ids") or sorted(groups) != receipt.get(
        "dev_leakage_groups"
    ):
        raise ValueError("签收的开发任务索引被修改")
    for task in _task_evidence(final_manifest):
        if task["task_id"] in task_ids or task["leakage_group"] in groups:
            raise ValueError("最终任务与开发集有任务 ID 或同修复组泄漏")
    return {**receipt, "receipt_sha256": file_sha256(receipt_path)}
