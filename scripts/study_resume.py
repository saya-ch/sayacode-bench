"""显式物理片边界恢复：离线冻结声明，Actions 原路径复核；不建立可变状态服务。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.release_evidence import _manifest
from sayacode_bench.shards import MERGE_ONLY_STOP_REASONS


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mapped_file(reference: dict[str, str], original: PurePosixPath, local: Path) -> Path:
    path = PurePosixPath(reference["path"])
    if (
        not path.is_absolute()
        or not path.is_relative_to(original)
        or ".." in path.parts
        or "\\" in str(path)
    ):
        raise ValueError("恢复引用不在原固定 bundle")
    target = local.joinpath(*path.relative_to(original).parts)
    if (
        not target.resolve().is_relative_to(local.resolve())
        or target.is_symlink()
        or file_sha256(target) != reference["sha256"]
    ):
        raise ValueError("恢复原件越界或字节身份不同")
    return target


def _history_pages(history: Any, field: str) -> list[dict[str, Any]]:
    """只接收完整分页快照；列表为空或 API 错误对象都不能解释为没有历史。"""
    if not isinstance(history, list) or not history:
        raise ValueError("Actions 历史缺少完整分页")
    rows: list[dict[str, Any]] = []
    for page in history:
        if (
            not isinstance(page, dict)
            or type(page.get("total_count")) is not int
            or not isinstance(page.get(field), list)
        ):
            raise ValueError("Actions 历史分页无效")
        rows.extend(page[field])
    if (
        any(page["total_count"] != len(rows) for page in history)
        or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in rows)
        or len({row["id"] for row in rows}) != len(rows)
        or any(row["id"] <= 0 for row in rows)
    ):
        raise ValueError("Actions 历史分页不完整或身份重复")
    return rows


def _resume_history(
    receipt: dict[str, Any], history: Any, jobs: dict[str, Any], *, current_run_id: int = 0
) -> list[dict[str, Any]]:
    """每个已启动 job 必须可解释；V1 不尝试修复失败或未知费用现场。"""
    rows = _history_pages(history, "workflow_runs")
    if any(not isinstance(row.get("display_title"), str) for row in rows):
        raise ValueError("Actions 历史缺少正式运行标题")
    title = "study " + receipt["master_sha256"]
    if current_run_id and not any(
        row["id"] == current_run_id and row.get("display_title") == title for row in rows
    ):
        raise ValueError("实时历史没有当前恢复运行")
    formal = [
        row
        for row in rows
        if re.fullmatch(r"study [0-9a-f]{64}", str(row.get("display_title", "")))
        and row["id"] != current_run_id
    ]
    same = [row for row in formal if row["display_title"] == title]
    if sorted(row["id"] for row in same) != receipt["prior_run_ids"]:
        raise ValueError("同 master 历史集合已改变，旧恢复收据失效")
    if sorted(row["id"] for row in formal) != receipt["budget_history_run_ids"]:
        raise ValueError("100 元范围历史已改变，冻结 prior 无法续入新费用；V1 拒绝恢复")
    if not same or set(jobs) != {str(row["id"]) for row in same}:
        raise ValueError("恢复缺少每个历史运行的 job 原件")
    # 没有全局费用服务，保守拒绝首个原运行之后的任何其他 master 正式派发。
    oldest = min(datetime.fromisoformat(row["created_at"]) for row in same)
    if any(
        row["display_title"] != title and datetime.fromisoformat(row["created_at"]) >= oldest
        for row in formal
    ):
        raise ValueError("暂停后有其他 master 派发，冻结 prior 无法续入其费用；V1 拒绝恢复")
    covered = []
    for run in same:
        if run.get("status") != "completed" or run.get("run_attempt") != 1:
            raise ValueError("历史 run 尚未 terminal 或曾重新运行")
        observed_review = False
        for job in _history_pages(jobs[str(run["id"])], "jobs"):
            if job.get("run_id") != run["id"] or job.get("status") != "completed":
                raise ValueError("历史 job 归属不明或仍在运行")
            name = job.get("name")
            if job.get("conclusion") == "skipped":
                if any(step.get("conclusion") != "skipped" for step in job.get("steps", [])):
                    raise ValueError("skipped job 仍有已启动步骤")
                continue
            if job.get("conclusion") != "success" or not job.get("started_at"):
                raise ValueError("历史 job 失败、启动状态或费用未知")
            if name == "review":
                observed_review = True
                continue
            if name == "merge / run":
                if receipt["prefix_length"] != receipt["schedule_length"]:
                    raise ValueError("未完整阶段存在已启动 final merge")
                continue
            match = re.fullmatch(r"shard_([0-9]{4}) / run", str(name))
            if match is None:
                raise ValueError("存在无法解释的已启动 job")
            sequence = int(match[1])
            if not 1 <= sequence <= receipt["prefix_length"]:
                raise ValueError("已启动 shard 超出完整前缀，禁止重跑")
            covered.append(
                {
                    "run_id": run["id"],
                    "job_id": job["id"],
                    "job_key": f"shard_{sequence:04d}",
                    "sequence": sequence,
                }
            )
        if not observed_review:
            raise ValueError("历史运行缺少成功 review")
    if sorted(item["sequence"] for item in covered) != list(range(1, receipt["prefix_length"] + 1)):
        raise ValueError("历史已启动 shard 必须恰好覆盖完整前缀一次")
    covered.sort(key=lambda item: item["sequence"])
    if receipt.get("started_shards") is not None and covered != receipt["started_shards"]:
        raise ValueError("历史 job 身份已改变")
    return covered


def _resume_binding(
    plan_path: Path, plan: dict[str, Any], master: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "immutable-prefix-resume",
        "plan_sha256": file_sha256(plan_path),
        "master_sha256": plan["master"]["sha256"],
        "schedule_sha256": plan["schedule_sha256"],
        "schedule_length": len(plan["schedule"]),
        "implementation": plan["implementation"],
        "financial_prior_sha256": _hash(
            [master.get("paid_budget"), plan.get("initial_paid_records", [])]
        ),
        "bundle_root": plan["bundle_root"],
        "native_validation_required": True,
    }


def _check_resume_files(receipt: dict[str, Any], plan: dict[str, Any], bundle: Path) -> None:
    original = PurePosixPath(plan["bundle_root"])
    tail = plan["schedule"][receipt["prefix_length"] - 1]
    expected = str(original / "shards" / tail["shard_id"] / "shard-receipt.json")
    if receipt["last_receipt"]["path"] != expected:
        raise ValueError("恢复末收据不属于声明的完整前缀")
    last = read_json(_mapped_file(receipt["last_receipt"], original, bundle))
    _mapped_file(receipt["ledger"], original, bundle)
    if (
        last.get("ledger_after") != receipt["ledger"]
        or last.get("sequence") != receipt["prefix_length"]
    ):
        raise ValueError("恢复末账本与前缀长度冲突")
    for job in receipt["started_shards"]:
        entry = plan["schedule"][job["sequence"] - 1]
        status = read_json(bundle / "orchestration" / entry["shard_id"] / "dispatch.json")
        native_path = bundle / "shards" / entry["shard_id"] / "shard-receipt.json"
        native = read_json(native_path)
        merge_only = (
            job["sequence"] == len(plan["schedule"])
            and native.get("stop_reason") in MERGE_ONLY_STOP_REASONS
            and native.get("continuation_allowed") is False
        )
        identity = {"run_id": job["run_id"], "run_attempt": 1, "job_key": job["job_key"]}
        if (
            status.get("actions_identity") != identity
            or status.get("plan_sha256") != receipt["plan_sha256"]
            or status.get("shard_id") != entry["shard_id"]
            or status.get("receipt_complete") is not True
            or status.get("continuation_allowed") is not (not merge_only)
            or native.get("complete") is not True
            or status.get("credential_cleanup_confirmed") is not True
            or status.get("host_cohort_confirmed") is not True
            or status.get("native_cli_returncode") != 0
            or status.get("error_type") is not None
            or status.get("receipt_sha256") != file_sha256(native_path)
            or status.get("ledger_sha256") != native["ledger_after"]["sha256"]
        ):
            raise ValueError("历史 job 缺少对应的完整原生派发及清理证据")


def freeze_resume_receipt(
    plan_path: Path,
    bundle: Path,
    output: Path,
    *,
    prefix_length: int,
    seed_manifest: Path,
    archive_receipt: Path,
    history: Path,
    jobs_directory: Path,
    plan: dict[str, Any],
    master: dict[str, Any],
    runner: dict[str, Any],
) -> dict[str, Any]:
    """离线冻结待原生核验的恢复声明；不把 Windows 路径映射当成执行签收。"""
    if type(prefix_length) is not int or not 1 <= prefix_length <= len(plan["schedule"]):
        raise ValueError("恢复长度必须是原 schedule 的非空连续前缀")
    manifest = read_json(seed_manifest)
    _manifest(manifest, **runner["evidence_release"])
    archive = read_json(archive_receipt)
    prior_history = json.loads(history.read_text(encoding="utf-8"))
    formal = [
        row
        for row in _history_pages(prior_history, "workflow_runs")
        if re.fullmatch(r"study [0-9a-f]{64}", str(row.get("display_title", "")))
    ]
    title = "study " + plan["master"]["sha256"]
    ids = sorted(row["id"] for row in formal if row["display_title"] == title)
    last = plan["schedule"][prefix_length - 1]
    local_receipt = bundle / "shards" / last["shard_id"] / "shard-receipt.json"
    native = read_json(local_receipt)
    receipt = {
        **_resume_binding(plan_path, plan, master),
        "prefix_length": prefix_length,
        "last_receipt": {
            "path": str(
                PurePosixPath(plan["bundle_root"])
                / "shards"
                / last["shard_id"]
                / "shard-receipt.json"
            ),
            "sha256": file_sha256(local_receipt),
        },
        "ledger": native["ledger_after"],
        "evidence_manifest": manifest,
        "archive_receipt": archive,
        "prior_run_ids": ids,
        "budget_history_run_ids": sorted(row["id"] for row in formal),
    }
    jobs = {
        str(run_id): json.loads((jobs_directory / f"{run_id}.json").read_text(encoding="utf-8"))
        for run_id in ids
    }
    receipt["started_shards"] = _resume_history(receipt, prior_history, jobs)
    _validate_resume(receipt, plan_path, plan, master, runner, bundle)
    write_json(output, receipt, exclusive=True)
    return receipt


def _validate_resume(
    receipt: dict[str, Any],
    plan_path: Path,
    plan: dict[str, Any],
    master: dict[str, Any],
    runner: dict[str, Any],
    bundle: Path,
) -> None:
    if any(
        receipt.get(key) != value for key, value in _resume_binding(plan_path, plan, master).items()
    ):
        raise ValueError("恢复收据的 plan/master/schedule/implementation/financial prior 已漂移")
    k = receipt.get("prefix_length")
    if type(k) is not int or not 1 <= k <= len(plan["schedule"]):
        raise ValueError("恢复前缀长度无效")
    for field in ("prior_run_ids", "budget_history_run_ids"):
        ids = receipt.get(field)
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(run_id) is not int or run_id <= 0 for run_id in ids)
            or ids != sorted(set(ids))
        ):
            raise ValueError("恢复历史 run IDs 必须完整、唯一且有序")
    if not set(receipt["prior_run_ids"]).issubset(receipt["budget_history_run_ids"]):
        raise ValueError("金融历史范围缺少当前 master")
    jobs = receipt.get("started_shards")
    if (
        not isinstance(jobs, list)
        or len(jobs) != k
        or any(
            not isinstance(job, dict)
            or job.get("sequence") != index
            or job.get("job_key") != f"shard_{index:04d}"
            or type(job.get("run_id")) is not int
            or type(job.get("job_id")) is not int
            or job.get("job_id", 0) <= 0
            or job.get("run_id") not in receipt["prior_run_ids"]
            for index, job in enumerate(jobs, 1)
        )
    ):
        raise ValueError("恢复收据缺少完整历史 shard/job 归属")
    manifest, archive = receipt["evidence_manifest"], receipt["archive_receipt"]
    _manifest(manifest, **runner["evidence_release"])
    last_job = receipt["started_shards"][-1]
    native = read_json(
        _mapped_file(receipt["last_receipt"], PurePosixPath(plan["bundle_root"]), bundle)
    )
    merge_only = k == len(plan["schedule"]) and native.get("stop_reason") in MERGE_ONLY_STOP_REASONS
    if (
        archive.get("transfer_status") != "completed"
        or archive.get("receipt_complete") is not True
        or archive.get("host_cohort_confirmed") is not True
        or archive.get("archive_sha256") != manifest["archive_sha256"]
        or archive.get("archive_bytes") != manifest["archive_size"]
        or archive.get("plan_sha256") != receipt["plan_sha256"]
        or archive.get("receipt_sha256") != receipt["last_receipt"]["sha256"]
        or archive.get("ledger_sha256") != receipt["ledger"]["sha256"]
        or archive.get("actions_identity")
        != {"run_id": last_job["run_id"], "run_attempt": 1, "job_key": last_job["job_key"]}
        or archive.get("shard_id") != plan["schedule"][k - 1]["shard_id"]
        or archive.get("continuation_allowed") is not (not merge_only)
    ):
        raise ValueError("末片 Release 归档上传或 Actions 归属未确认")
    _check_resume_files(receipt, plan, bundle)
