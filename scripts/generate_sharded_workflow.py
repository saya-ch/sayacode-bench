"""从冻结计划生成原生 Actions 串行 DAG；云端辅助命令只调用现有研究 CLI。

本文件不会授权正式试验。完整原始 bundle 交给固定私有 draft Release；
Actions 仅保本片原始数据三天。账户零美元预算不变，不承诺永久免费。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.execution import paired_order
from sayacode_bench.release_evidence import (
    BILLING_BOUNDARY,
    _manifest,
    download_archive,
    upload_archive,
)
from scripts import study_resume

EXECUTION_REPOSITORY = "saya-ch/sayacode-bench-runs"
PUBLIC_REPOSITORY = "saya-ch/sayacode-bench"
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
TEMPLATE = Path(__file__).resolve().parents[1] / ".github/workflows/run-study-shard.yml"
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
LABEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}\Z")
STORAGE_NOTE = (
    "完整原始 bundle 每片累积并保留三天；500 MB 免费 artifact 存储不是充分条件。"
    "需人工核实分钟、存储及计费授权；下载核验前不得删除云端证据，本脚本不删除 artifact。"
)
HOST_FIELDS = ("ImageOS", "ImageVersion", "RUNNER_ARCH")
HOST_EXCLUSIONS = ("physical_cpu_identity", "kernel_identity", "provider_model_immutability")
MAX_MANIFEST_CHARACTERS = 48_000


def _release(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"repository", "release_id", "release_tag"}
        or value["repository"] != EXECUTION_REPOSITORY
        or type(value["release_id"]) is not int
        or value["release_id"] <= 0
        or not isinstance(value["release_tag"], str)
        or not value["release_tag"].strip()
        or any(char in value["release_tag"] for char in "\r\n\0")
    ):
        raise ValueError("需要冻结的私有 draft Release 身份")
    return dict(value)


def _manifest_json(value: dict[str, Any], release: dict[str, Any]) -> str:
    _manifest(value, **_release(release))
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    if len(text) > MAX_MANIFEST_CHARACTERS:
        raise ValueError("Release manifest 超过安全的 Actions 单行输出范围")
    return text


def guard_study_dispatch(history: Any, master_sha256: str, run_id: int) -> None:
    """同一 master 首次派发不得重置账本；恢复必须使用显式收据入口。"""
    if (
        not SHA.fullmatch(master_sha256)
        or type(run_id) is not int
        or run_id <= 0
        or not isinstance(history, list)
        or not history
    ):
        raise ValueError("正式派发身份或 Actions 历史未确认")
    rows: list[dict[str, Any]] = []
    totals = []
    for page in history:
        if (
            not isinstance(page, dict)
            or type(page.get("total_count")) is not int
            or not isinstance(page.get("workflow_runs"), list)
        ):
            raise ValueError("Actions 历史分页未确认")
        totals.append(page["total_count"])
        rows.extend(page["workflow_runs"])
    if any(
        not isinstance(row, dict)
        or type(row.get("id")) is not int
        or row["id"] <= 0
        or not isinstance(row.get("display_title"), str)
        for row in rows
    ):
        raise ValueError("Actions 原生运行身份未确认")
    if totals != [len(rows)] * len(totals) or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Actions 历史覆盖不完整或存在冲突")
    title = f"study {master_sha256}"
    if not any(row["id"] == run_id and row["display_title"] == title for row in rows):
        raise ValueError("Actions 历史缺少当前正式运行")
    if any(row["id"] != run_id and row["display_title"] == title for row in rows):
        raise ValueError(
            "同 master 已有正式派发，不得从空账本重启；必须使用显式、仍有效的 prefix 恢复收据"
        )


def _host_cohort(value: Any) -> dict[str, str]:
    """只约束宿主镜像声明，不把三字段相同扩大为硬件或模型相同。"""
    if (
        not isinstance(value, dict)
        or set(value) != set(HOST_FIELDS)
        or any(not isinstance(item, str) or not item.strip() for item in value.values())
        or value.get("RUNNER_ARCH") != "X64"
    ):
        raise ValueError("runner 政策必须固定三字段宿主镜像 cohort")
    return {key: value[key] for key in HOST_FIELDS}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _archive_digest(path: Path) -> str:
    """完整 raw bundle 可能很大，校验不把整个 tar 载入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\n" in value:
        raise ValueError("需要 bundle 内的相对 POSIX 路径")
    return path


def _local(root: Path, relative: str) -> Path:
    result = root.joinpath(*_relative(relative).parts)
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise ValueError("工件路径越过 bundle")
    return result


def _mapped(reference: dict[str, str], original: PurePosixPath, local: Path) -> Path:
    path = PurePosixPath(reference["path"])
    if not path.is_relative_to(original):
        raise ValueError("冻结工件不在固定 Linux bundle")
    target = _local(local, str(path.relative_to(original)))
    if not SHA.fullmatch(reference["sha256"]) or file_sha256(target) != reference["sha256"]:
        raise ValueError("冻结工件字节身份不同")
    return target


def inspect_plan(
    plan_path: Path, bundle: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """本机可映射读取 Linux bundle，原始 JSON 路径从不重写。"""
    plan = read_json(plan_path)
    original = PurePosixPath(plan["bundle_root"])
    if (
        plan.get("schema_version") != 1
        or original.parent != PurePosixPath("/tmp/sayacode-studies")
        or not LABEL.fullmatch(original.name)
    ):
        raise ValueError("需要固定 Linux study bundle")
    master = read_json(_mapped(plan["master"], original, bundle))
    runner = read_json(_mapped(plan["runner_policy"], original, bundle))
    _host_cohort(runner.get("host_cohort"))
    from sayacode_bench.shards import qualification_host_cohort

    qualified_cohort = qualification_host_cohort(master)
    if qualified_cohort is not None and qualified_cohort != runner["host_cohort"]:
        raise ValueError("正式 runner 与公开资格的宿主镜像 cohort 不同")
    _release(runner.get("evidence_release"))
    authorization = read_json(_mapped(plan["authorization"], original, bundle))
    if (
        master.get("frozen") is not True
        or master.get("phase") not in {"dev", "holdout", "validation", "calibration"}
        or authorization.get("authorized") is not True
        or authorization.get("phase") != master["phase"]
        or authorization.get("master_manifest_sha256") != plan["master"]["sha256"]
        or runner.get("platform") != "linux"
        or runner.get("architecture") != "amd64"
        or runner.get("job_timeout_seconds") != 21600
        or not COMMIT.fullmatch(str(runner.get("public_source_sha", "")))
        or runner.get("executor_workflow_sha256") != file_sha256(TEMPLATE)
        or plan.get("implementation") != implementation_identity()
        or plan.get("artifacts") != master.get("artifacts")
    ):
        raise ValueError("计划、授权、源码、模板或 runner 政策未绑定")
    if any("api_key" in profile for profile in master.get("connection_profiles", {}).values()):
        raise ValueError("master 不得包含私有密钥")
    expected = paired_order(master)
    schedule = plan["schedule"]
    if not schedule or len(schedule) != len(expected) or _hash(schedule) != plan["schedule_sha256"]:
        raise ValueError("全 master schedule 身份不一致")
    for actual, row in zip(schedule, expected, strict=True):
        task = next(task for task in master["tasks"] if task["task_id"] == row["task_id"])
        reserve = math.ceil(
            2
            * (
                task["environment"]["build_timeout_sec"]
                + task["agent"]["timeout_sec"]
                + task["verifier"]["timeout_sec"]
            )
            + 1200
            + 900
        )
        key = _hash([plan["master"]["sha256"], row["task_id"], row["configuration"], row["repeat"]])
        endpoint = master["connections"][(row["repeat"] - 1) % len(master["connections"])]
        if (
            any(actual.get(field) != value for field, value in row.items())
            or actual.get("trial_key") != key
            or actual.get("block_id")
            != _hash([plan["master"]["sha256"], row["task_id"], row["repeat"]])
            or actual.get("shard_id") != f"{master['phase']}-{row['sequence']:04d}-{key[:12]}"
            or actual.get("endpoint") != endpoint
            or actual.get("reserve_seconds") != reserve
            or not 0 < reserve <= 21600
        ):
            raise ValueError("顺序、连接、试验键或官方时限不一致")
    return plan, master, runner


def _artifact_bindings(bundle: Path, digests: dict[str, Any]) -> dict[str, Any]:
    """按冻结 SHA 唯一定位输入，不通过文件名猜测或修改候选。"""
    files: dict[str, list[str]] = {}
    for path in sorted((bundle / "inputs").rglob("*")):
        if path.is_file() and not path.is_symlink():
            files.setdefault(file_sha256(path), []).append(path.relative_to(bundle).as_posix())

    def locate(digest: str) -> str:
        matches = files.get(digest, [])
        if len(matches) != 1:
            raise ValueError("生产工件 SHA 必须在 inputs 中唯一存在")
        return matches[0]

    return {
        "wheel": locate(digests["product_wheel"]),
        "requirements": locate(digests["requirements"]),
        "variants": {label: locate(digest) for label, digest in digests["variants"].items()},
    }


def generate(
    plan_path: Path,
    bundle: Path,
    output: Path,
    *,
    seed_manifest: Path,
    resume_receipt: Path | None = None,
    through_sequence: int | None = None,
) -> dict[str, Any]:
    """只生成可审阅文件，不访问 GitHub、Docker、凭据或模型。"""
    if output.exists() or output.with_suffix(".receipt.json").exists():
        raise FileExistsError("生成工作流不可覆盖")
    plan, master, runner = inspect_plan(plan_path, bundle)
    initial_manifest = read_json(seed_manifest)
    initial_manifest_json = _manifest_json(initial_manifest, runner["evidence_release"])
    resume = read_json(resume_receipt) if resume_receipt is not None else None
    prefix = 0
    if resume is not None:
        study_resume._validate_resume(resume, plan_path, plan, master, runner, bundle)
        if initial_manifest != resume["evidence_manifest"]:
            raise ValueError("恢复种子必须是收据冻结的完整 Release 归档")
        prefix = resume["prefix_length"]
    through = len(plan["schedule"]) if through_sequence is None else through_sequence
    if (
        type(through) is not int
        or not max(1, prefix) <= through <= len(plan["schedule"])
        or (prefix < len(plan["schedule"]) and through <= prefix)
    ):
        raise ValueError("本次物理批次终点必须晚于完整前缀且不超过全 schedule")
    contract = {
        "schema_version": 1,
        "public_source_sha": runner["public_source_sha"],
        "plan_sha256": file_sha256(plan_path),
        "master_sha256": plan["master"]["sha256"],
        "merge_relative_directory": "merged/" + plan["master"]["sha256"],
        "through_sequence": through,
        "plan_relative_path": plan_path.resolve().relative_to(bundle.resolve()).as_posix(),
        "bundle_root": plan["bundle_root"],
        "private_home": f"/tmp/sayacode-private/{PurePosixPath(plan['bundle_root']).name}",
        "executor_workflow_sha256": file_sha256(TEMPLATE),
        "generator_sha256": file_sha256(Path(__file__)),
        "host_cohort": runner["host_cohort"],
        "evidence_release": runner["evidence_release"],
        "bindings": _artifact_bindings(bundle, plan["artifacts"]),
        "resume_receipt": resume,
        "resume_receipt_sha256": _hash(resume) if resume is not None else None,
        "resume_helper_sha256": file_sha256(Path(study_resume.__file__)),
    }
    text = json.dumps(contract, ensure_ascii=False, separators=(",", ":"))
    execute_condition = "${{ inputs.execute_models && inputs.confirm_formal_scope && inputs.confirm_actions_budget }}"
    jobs: dict[str, Any] = {
        "review": {
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 5,
            "steps": [
                {
                    "name": "只审阅；正式执行须另获授权及额度确认",
                    "env": {"GH_TOKEN": "${{ github.token }}"},
                    "shell": "bash",
                    "run": PRIVATE_GUARD,
                },
                {
                    "if": execute_condition,
                    "uses": CHECKOUT,
                    "with": {
                        "repository": PUBLIC_REPOSITORY,
                        "ref": runner["public_source_sha"],
                        "path": "bench",
                        "persist-credentials": False,
                    },
                },
                {
                    "if": execute_condition,
                    "uses": "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e",
                    "with": {
                        "version": "0.12.5",
                        "python-version": "3.13.12",
                        "enable-cache": False,
                    },
                },
                {"if": execute_condition, "working-directory": "bench", "run": "uv sync --frozen"},
                {
                    "if": execute_condition,
                    "name": "核验同 master 的首次正式派发，预览不占正式身份",
                    "working-directory": "bench",
                    "shell": "bash",
                    "env": {
                        "GH_TOKEN": "${{ github.token }}",
                        "MASTER_SHA": plan["master"]["sha256"],
                    },
                    "run": 'set -eu\ngh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/runs?per_page=100" > "$RUNNER_TEMP/study-history.json"\nuv run --no-sync python -m scripts.generate_sharded_workflow dispatch-guard --history "$RUNNER_TEMP/study-history.json" --master-sha256 "$MASTER_SHA" --run-id "$GITHUB_RUN_ID"',
                },
            ],
        }
    }
    if resume is not None:
        review_steps = jobs["review"]["steps"]
        review_steps[-1] = {
            "if": execute_condition,
            "name": "原 Linux 路径核验恢复前缀，并重新枚举全部 run/job 历史",
            "working-directory": "bench",
            "shell": "bash",
            "env": {
                "GH_TOKEN": "${{ github.token }}",
                "SAYACODE_STUDY_CONTRACT": text,
                "SAYACODE_EVIDENCE_MANIFEST": initial_manifest_json,
            },
            "run": RESUME_REVIEW,
        }
        jobs["review"]["timeout-minutes"] = 60
    for index in range(prefix + 1, through + 1):
        entry = plan["schedule"][index - 1]
        previous = f"shard_{index - 1:04d}" if index > prefix + 1 else "review"
        condition = (
            "always() && !cancelled() && inputs.execute_models && "
            "inputs.confirm_formal_scope && inputs.confirm_actions_budget && "
            f"needs.{previous}.result == 'success'"
        )
        if index > prefix + 1:
            condition += f" && needs.{previous}.outputs.continuation_allowed == 'true'"
        arguments = {
            "contract_json": text,
            "shard_id": entry["shard_id"],
            "mode": "shard",
            "job_key": f"shard_{index:04d}",
            "evidence_manifest_json": initial_manifest_json
            if index == prefix + 1
            else f"${{{{ needs.{previous}.outputs.evidence_manifest_json }}}}",
            "previous_receipt_sha256": (resume["last_receipt"]["sha256"] if resume else "")
            if index == prefix + 1
            else f"${{{{ needs.{previous}.outputs.receipt_sha256 }}}}",
            "previous_ledger_sha256": (resume["ledger"]["sha256"] if resume else "")
            if index == prefix + 1
            else f"${{{{ needs.{previous}.outputs.ledger_sha256 }}}}",
        }
        jobs[f"shard_{index:04d}"] = {
            "name": f"shard_{index:04d}",
            "needs": [previous],
            "if": "${{ " + condition + " }}",
            "uses": "./.github/workflows/run-study-shard.yml",
            "with": arguments,
            "secrets": {"connection_keys_json": "${{ secrets.STUDY_CONNECTION_KEYS_JSON }}"},
        }
    last = f"shard_{through:04d}" if prefix < through else "review"
    if through == len(plan["schedule"]):
        jobs["merge"] = {
            "name": "merge",
            "needs": [last],
            "if": "${{ always() && !cancelled() && inputs.execute_models && inputs.confirm_formal_scope && inputs.confirm_actions_budget && needs."
            + last
            + ".result == 'success' }}",
            "uses": "./.github/workflows/run-study-shard.yml",
            "with": {
                "contract_json": text,
                "mode": "merge",
                "job_key": "merge",
                "shard_id": "",
                "evidence_manifest_json": initial_manifest_json
                if last == "review"
                else f"${{{{ needs.{last}.outputs.evidence_manifest_json }}}}",
                "previous_receipt_sha256": resume["last_receipt"]["sha256"]
                if last == "review" and resume
                else f"${{{{ needs.{last}.outputs.receipt_sha256 }}}}",
                "previous_ledger_sha256": resume["ledger"]["sha256"]
                if last == "review" and resume
                else f"${{{{ needs.{last}.outputs.ledger_sha256 }}}}",
            },
        }
    workflow = {
        "name": f"冻结研究 {master['phase']} {contract['plan_sha256'][:12]}",
        "run-name": "${{ inputs.execute_models && inputs.confirm_formal_scope && inputs.confirm_actions_budget && 'study "
        + plan["master"]["sha256"]
        + "' || 'review study "
        + plan["master"]["sha256"]
        + "' }}",
        "on": {
            "workflow_dispatch": {
                "inputs": {
                    key: {"description": description, "type": "boolean", "default": False}
                    for key, description in (
                        ("execute_models", "实际执行冻结阶段；默认只审阅"),
                        ("confirm_formal_scope", "已另行获得这份完整阶段和路由的执行授权"),
                        ("confirm_actions_budget", "已核实 Actions 分钟、增长存储和计费范围"),
                    )
                }
            }
        },
        "permissions": {"contents": "write", "actions": "read"},
        "concurrency": {"group": "sayacode-study-global", "cancel-in-progress": False},
        "jobs": jobs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # JSON 是 YAML 的子集，避免引入另一个 YAML 生成器或非标准表达式转义。
    output.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "plan_sha256": contract["plan_sha256"],
        "schedule_sha256": plan["schedule_sha256"],
        "public_source_sha": runner["public_source_sha"],
        "executor_workflow_sha256": contract["executor_workflow_sha256"],
        "generator_sha256": contract["generator_sha256"],
        "workflow_sha256": file_sha256(output),
        "seed_manifest_sha256": file_sha256(seed_manifest),
        "seed_archive_sha256": initial_manifest["archive_sha256"],
        "shard_count": len(plan["schedule"]),
        "dispatched_shard_count": through - prefix,
        "resume_prefix_length": prefix,
        "through_sequence": through,
        "physical_batch_only": through < len(plan["schedule"]),
        "native_resume_validation_performed": False,
        "planned_reserve_seconds": sum(row["reserve_seconds"] for row in plan["schedule"]),
        "actions_artifact_retention_days": 3,
        "storage_note": BILLING_BOUNDARY,
        "execution_authorized_by_generation": False,
        "host_cohort_enforced": True,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
    }
    write_json(output.with_suffix(".receipt.json"), receipt, exclusive=True)
    return receipt


PRIVATE_GUARD = """set -eu
test "$GITHUB_REPOSITORY" = saya-ch/sayacode-bench-runs
test "$GITHUB_RUN_ATTEMPT" = 1
gh api "repos/$GITHUB_REPOSITORY" > "$RUNNER_TEMP/repository.json"
python - <<'PY'
import json, os
from pathlib import Path
d = json.loads((Path(os.environ['RUNNER_TEMP'])/'repository.json').read_text(encoding='utf-8'))
assert d.get('full_name') == 'saya-ch/sayacode-bench-runs'
assert d.get('private') is True and d.get('visibility') == 'private'
PY
"""


RESUME_REVIEW = """set -eu
uv run --no-sync python -m scripts.generate_sharded_workflow restore --download-dir "$RUNNER_TEMP/resume-incoming"
gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/runs?per_page=100" > "$RUNNER_TEMP/study-history.json"
mkdir "$RUNNER_TEMP/resume-jobs"
python - <<'PY' > "$RUNNER_TEMP/resume-run-ids"
import json, os
for run_id in json.loads(os.environ['SAYACODE_STUDY_CONTRACT'])['resume_receipt']['prior_run_ids']:
    assert type(run_id) is int and run_id > 0
    print(run_id)
PY
while read -r run_id; do
  gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/jobs?filter=all&per_page=100" > "$RUNNER_TEMP/resume-jobs/$run_id.json"
done < "$RUNNER_TEMP/resume-run-ids"
uv run --no-sync python -m scripts.generate_sharded_workflow resume-review --history "$RUNNER_TEMP/study-history.json" --jobs-directory "$RUNNER_TEMP/resume-jobs" --run-id "$GITHUB_RUN_ID"
"""


def restore_archive(archive: Path, target: Path, expected_sha256: str) -> None:
    """只恢复完整私有 tar；拒绝路径逃逸、外部链接和现存目录。"""
    if not SHA.fullmatch(expected_sha256) or _archive_digest(archive) != expected_sha256:
        raise ValueError("bundle tar SHA256 不同")
    if target.exists() or target.is_symlink():
        raise FileExistsError("fresh runner 不能覆盖原 bundle")
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        names = set()
        total = 0
        for member in members:
            name = _relative(member.name)
            if str(name) in names or not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("重复路径或不支持的 tar 成员")
            names.add(str(name))
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts or "\\" in member.linkname:
                    raise ValueError("拒绝外部或不明确的符号链接")
            total += member.size
        target.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(target.parent).free < total + 12 * 1024**3:
            raise ValueError("恢复完整证据后不足官方镜像所需磁盘余量")
        target.mkdir(exist_ok=False)
        stream.extractall(target, members=members, filter="data")


def load_contract(
    text: str, bundle: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = json.loads(text)
    root = bundle or Path(contract["bundle_root"])
    path = _local(root, contract["plan_relative_path"])
    if file_sha256(path) != contract["plan_sha256"]:
        raise ValueError("计划 SHA 与生成 DAG 不同")
    plan, master, runner = inspect_plan(path, root)
    if (
        contract["bundle_root"] != plan["bundle_root"]
        or contract["public_source_sha"] != runner["public_source_sha"]
        or contract["executor_workflow_sha256"] != file_sha256(TEMPLATE)
        or contract["generator_sha256"] != file_sha256(Path(__file__))
        or contract.get("host_cohort") != runner["host_cohort"]
        or contract.get("evidence_release") != runner["evidence_release"]
        or contract.get("master_sha256") != plan["master"]["sha256"]
        or contract.get("merge_relative_directory") != "merged/" + plan["master"]["sha256"]
        or contract.get("resume_helper_sha256") != file_sha256(Path(study_resume.__file__))
        or contract["bindings"] != _artifact_bindings(root, plan["artifacts"])
    ):
        raise ValueError("生成器、工件或模板已漂移")
    return contract, plan, master


def verify_resume_contract(
    contract_text: str, *, shard_id: str = "", mode: str = "review"
) -> dict[str, Any] | None:
    """review 与首个剩余片在无模型 Secret 步骤调用同一原生核验。"""
    contract, plan, master = load_contract(contract_text)
    resume = contract.get("resume_receipt")
    if resume is None:
        return None
    if _hash(resume) != contract.get("resume_receipt_sha256"):
        raise ValueError("恢复收据字节声明已改变")
    if mode not in {"review", "shard", "merge"} or (mode != "shard" and shard_id):
        raise ValueError("恢复核验模式不明确")
    bundle = Path(plan["bundle_root"])
    plan_path = _local(bundle, contract["plan_relative_path"])
    runner = read_json(_mapped(plan["runner_policy"], PurePosixPath(plan["bundle_root"]), bundle))
    study_resume._validate_resume(resume, plan_path, plan, master, runner, bundle)
    if mode == "shard":
        if resume["prefix_length"] == len(plan["schedule"]):
            raise ValueError("完整前缀只能归并，不能再次派发 source")
        if not any(
            entry["shard_id"] == shard_id for entry in plan["schedule"][resume["prefix_length"] :]
        ):
            raise ValueError("恢复只能派发原前缀之后的试验")
        if shard_id != plan["schedule"][resume["prefix_length"]]["shard_id"]:
            return None
    from sayacode_bench.shards import verify_resume_prefix

    length = len(plan["schedule"]) if mode == "merge" else resume["prefix_length"]
    native: dict[str, Any] = verify_resume_prefix(plan_path, length)
    ancestor = native["last_receipt"]
    # 恢复后最终归并核验全 N，并证明它仍从冻结的 k 收据延续，不能重验“k 后为空”。
    for _ in range(length - resume["prefix_length"]):
        ancestor = read_json(Path(ancestor["path"]))["previous_receipt"]
    if ancestor != resume["last_receipt"] or (
        length == resume["prefix_length"] and native["ledger"] != resume["ledger"]
    ):
        raise ValueError("原生恢复前缀与冻结收据不同")
    return native


def _actions_identity() -> dict[str, Any] | None:
    # 普通 CI 也有 GITHUB_RUN_ID；只有正式 reusable job 显式提供本地 job key。
    key = os.environ.get("SAYACODE_ACTIONS_JOB_KEY")
    if not key:
        return None
    run_id = int(os.environ["GITHUB_RUN_ID"])
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    if run_id <= 0 or attempt != 1 or re.fullmatch(r"shard_[0-9]{4}|merge", key) is None:
        raise ValueError("Actions run/job 归属无效")
    return {"run_id": run_id, "run_attempt": attempt, "job_key": key}


def _merge_directory(plan: dict[str, Any]) -> Path:
    destination: Path = Path(plan["bundle_root"]) / "merged" / plan["master"]["sha256"]
    return destination


def verify_previous(
    plan: dict[str, Any], entry: dict[str, Any] | None, receipt_sha: str, ledger_sha: str
) -> Path | None:
    sequence = entry["sequence"] - 1 if entry else len(plan["schedule"])
    if not sequence:
        if receipt_sha or ledger_sha:
            raise ValueError("首片不能夹带前序账本")
        return None
    previous = plan["schedule"][sequence - 1]
    path: Path = Path(plan["bundle_root"]) / "shards" / previous["shard_id"] / "shard-receipt.json"
    value = read_json(path)
    ledger = Path(value["ledger_after"]["path"])
    if (
        not SHA.fullmatch(receipt_sha)
        or file_sha256(path) != receipt_sha
        or not SHA.fullmatch(ledger_sha)
        or value["ledger_after"]["sha256"] != ledger_sha
        or file_sha256(ledger) != ledger_sha
        or (entry is not None and value.get("continuation_allowed") is not True)
    ):
        raise ValueError("下载的前序 receipt 或累计账本未通过")
    return path


async def prepare_image(master: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """复用已存在的固定 digest 拉取函数；不改官方 task 文件。"""
    from scripts.diagnose_fixtures import pin_image

    task = next(task for task in master["tasks"] if task["task_id"] == entry["task_id"])
    runtime = master["qualified_runtime_identities"][entry["task_id"]]
    original = task["environment"]["docker_image"]
    repository = original.rsplit(":", 1)[0]
    matches = [
        value
        for value in runtime.get("repo_digests", [])
        if value.startswith(repository + "@sha256:")
    ]
    if len(matches) != 1:
        raise ValueError("冻结资格缺少唯一原镜像 RepoDigest，不能猜测 tag")
    result = await pin_image({"immutable_image": matches[0], "original_image_reference": original})
    if (
        result["expected_image_id"] != runtime["image_id"]
        or result["os"] != "linux"
        or result["architecture"] != "amd64"
    ):
        raise ValueError("拉取的官方镜像与资格身份不同")
    return result


def _cli(arguments: list[str], log: Path, *, deadline: float | None = None) -> int:
    environment = dict(os.environ)
    environment.pop("SAYACODE_STUDY_CONNECTION_KEYS_JSON", None)
    environment.pop("GH_TOKEN", None)
    environment.pop("GITHUB_TOKEN", None)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        result = subprocess.run(
            [sys.executable, "-m", "sayacode_bench.cli", *arguments],
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=max(1, deadline - time.time()) if deadline is not None else None,
            check=False,
        )
    return result.returncode


def _private_directory(contract: dict[str, Any], bundle: Path) -> Path:
    private = Path(contract["private_home"])
    if private != Path("/tmp/sayacode-private") / bundle.name or private.is_relative_to(bundle):
        raise ValueError("私有 profile 路径不符合固定布局")
    return private


def execute(
    contract_text: str,
    shard_id: str,
    *,
    probe: Path,
    runner_preparation: Path,
    deadline: float,
    receipt_sha: str = "",
    ledger_sha: str = "",
) -> dict[str, Any]:
    """只建立本片私有连接并调用生产 CLI，不实现 Agent 或评分循环。"""
    contract, plan, master = load_contract(contract_text)
    bundle = Path(plan["bundle_root"])
    entry = next(row for row in plan["schedule"] if row["shard_id"] == shard_id)
    if contract.get("resume_receipt") is not None:
        verify_resume_contract(contract_text, shard_id=shard_id, mode="shard")
    directory = bundle / "orchestration" / shard_id
    directory.mkdir(parents=True, exist_ok=False)
    status: dict[str, Any] = {
        "plan_sha256": contract.get("plan_sha256"),
        "shard_id": shard_id,
        "actions_identity": _actions_identity(),
        "physical_batch_complete": False,
        "model_dispatch_attempted": False,
        "receipt_complete": False,
        "continuation_allowed": False,
        "error_type": None,
        "host_cohort_confirmed": False,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
    }
    private = _private_directory(contract, bundle)
    created = False
    profiles: list[Path] = []
    try:
        prepared = read_json(runner_preparation)
        write_json(directory / "runner-preparation.json", prepared, exclusive=True)
        status["runner_preparation_sha256"] = file_sha256(runner_preparation)
        status["expected_host_cohort"] = _host_cohort(contract.get("host_cohort"))
        status["observed_host_cohort"] = prepared.get("runner_image")
        if (
            prepared.get("passed") is not True
            or prepared.get("script_sha256")
            != file_sha256(Path(__file__).with_name("prepare_cloud_runner.py"))
            or prepared.get("runner_image") != status["expected_host_cohort"]
        ):
            raise ValueError("当前宿主镜像 cohort 或准备脚本与冻结政策不同")
        status["host_cohort_confirmed"] = True
        before = verify_previous(plan, entry, receipt_sha, ledger_sha)
        observed = read_json(probe)
        if (
            observed.get("passed") is not True
            or observed.get("cleanup_confirmed") is not True
            or observed.get("source_sha256", {}).get("network.py")
            != implementation_identity()["network.py"]
            or not math.isfinite(deadline)
            or time.time() + entry["reserve_seconds"] > deadline
        ):
            raise ValueError("本 runner 网络、清理或官方时间余量不足")
        write_json(directory / "network-probe.json", observed, exclusive=True)
        write_json(
            directory / "image-preparation.json",
            asyncio.run(prepare_image(master, entry)),
            exclusive=True,
        )
        if (
            time.time() + entry["reserve_seconds"] > deadline
            or shutil.disk_usage(bundle).free < 12 * 1024**3
        ):
            raise ValueError("镜像准备后时间或磁盘不足，不启动模型")
        # 连接参数来自完整 master，只有 key 来自本次显式 Secret；不打印正文。
        keys = json.loads(os.environ.get("SAYACODE_STUDY_CONNECTION_KEYS_JSON", "{}"))
        if set(keys) != set(master["connections"]) or any(
            not isinstance(value, str) or not value for value in keys.values()
        ):
            raise ValueError("显式连接密钥与冻结连接集合不同")
        private.mkdir(parents=True, exist_ok=False)
        private.chmod(0o700)
        created = True
        arguments = [
            "run-shard",
            "--plan",
            str(_local(bundle, contract["plan_relative_path"])),
            "--shard-id",
            shard_id,
            "--cache",
            str(bundle / "cache"),
            "--output",
            str(bundle / "shards" / shard_id),
            "--private-home",
            str(private),
            "--deadline-epoch",
            str(deadline),
        ]
        if before:
            arguments += ["--previous-receipt", str(before)]
        for label in master["connections"]:
            if not LABEL.fullmatch(label):
                raise ValueError("非法连接别名")
            path = private / f"{label}.json"
            profiles.append(path)
            write_json(
                path,
                {**master["connection_profiles"][label], "api_key": keys[label]},
                exclusive=True,
            )
            path.chmod(0o600)
            arguments += ["--connection", f"{label}={path}"]
        bindings = contract["bindings"]
        arguments += [
            "--wheel",
            str(_local(bundle, bindings["wheel"])),
            "--requirements",
            str(_local(bundle, bindings["requirements"])),
        ]
        for label, value in bindings["variants"].items():
            arguments += ["--variant", f"{label}={_local(bundle, value)}"]
        status["model_dispatch_attempted"] = True
        status["native_cli_returncode"] = _cli(
            arguments, directory / "entry.log", deadline=deadline + 300
        )
        path = bundle / "shards" / shard_id / "shard-receipt.json"
        receipt = read_json(path)
        status.update(
            {
                "receipt_sha256": file_sha256(path),
                "ledger_sha256": receipt["ledger_after"]["sha256"],
                "receipt_complete": receipt.get("complete") is True,
                "continuation_allowed": receipt.get("continuation_allowed") is True
                and status["native_cli_returncode"] == 0,
            }
        )
        status["merge_cli_returncode"] = merge(
            contract_text, output=_merge_directory(plan) / f"prefix-{entry['sequence']:04d}"
        )
        # 未完整前缀返回 1 是原 CLI 的既定语义；异常参数/身份返回 2 必须止损。
        if status["merge_cli_returncode"] not in {0, 1}:
            raise ValueError("严格归并失败，不允许后续派发")
    except Exception as exc:
        status["error_type"] = type(exc).__name__
        status["continuation_allowed"] = False
    finally:
        if created:
            try:
                for path in profiles:
                    path.unlink(missing_ok=True)
                for label in master["connections"]:
                    (private / "runs" / "run" / f"{label}-gateway.json").unlink(missing_ok=True)
                for path in (private / "runs" / "run", private / "runs", private):
                    if path.is_dir():
                        path.rmdir()
                status["credential_cleanup_confirmed"] = True
            except OSError as exc:
                status["credential_cleanup_confirmed"] = False
                status["continuation_allowed"] = False
                status["error_type"] = type(exc).__name__
        status["physical_batch_complete"] = bool(
            status["receipt_complete"]
            and status.get("native_cli_returncode") == 0
            and status.get("credential_cleanup_confirmed") is True
            and status["error_type"] is None
            and entry["sequence"] == contract.get("through_sequence")
        )
        write_json(directory / "dispatch.json", status, exclusive=True)
    return status


def merge(contract_text: str, *, output: Path | None = None) -> int:
    contract, plan, _ = load_contract(contract_text)
    bundle = Path(plan["bundle_root"])
    receipts = [
        bundle / "shards" / row["shard_id"] / "shard-receipt.json" for row in plan["schedule"]
    ]
    receipts = [path for path in receipts if path.is_file()]
    if not receipts:
        return 1
    destination = output or _merge_directory(plan) / "final"
    arguments = [
        "merge-shards",
        "--plan",
        str(_local(bundle, contract["plan_relative_path"])),
        "--output",
        str(destination),
    ]
    for path in receipts:
        arguments += ["--receipt", str(path)]
    return _cli(
        arguments,
        bundle / "orchestration" / plan["master"]["sha256"] / f"merge-{destination.name}.log",
    )


def archive_bundle(contract_text: str, output: Path, *, shard_id: str) -> dict[str, Any]:
    """不裁剪原生证据、不自动删除旧工件；归档失败会阻止后序。"""
    contract = json.loads(contract_text)
    bundle = Path(contract["bundle_root"])
    if output.resolve().is_relative_to(bundle.resolve()):
        raise ValueError("归档文件必须位于完整 bundle 外部")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as stream:
        for path in sorted(bundle.iterdir()):
            stream.add(path, arcname=path.name, recursive=True)
    status_path = bundle / "orchestration" / shard_id / "dispatch.json"
    status = read_json(status_path) if shard_id and status_path.is_file() else {}
    result = {
        "schema_version": 1,
        "plan_sha256": contract["plan_sha256"],
        "shard_id": shard_id,
        "actions_identity": _actions_identity(),
        "archive_sha256": _archive_digest(archive),
        "archive_bytes": archive.stat().st_size,
        "receipt_sha256": status.get("receipt_sha256", ""),
        "ledger_sha256": status.get("ledger_sha256", ""),
        "receipt_complete": status.get("receipt_complete") is True,
        "host_cohort_confirmed": status.get("host_cohort_confirmed") is True,
        "host_cohort_fields": list(HOST_FIELDS),
        "host_cohort_exclusions": list(HOST_EXCLUSIONS),
        "continuation_allowed": status.get("continuation_allowed") is True,
        "physical_batch_complete": status.get("physical_batch_complete") is True,
        "actions_artifact_retention_days": 3,
        "storage_note": BILLING_BOUNDARY,
        "contains_private_raw_evidence": True,
        "cloud_artifact_deletion_performed": False,
    }
    receipt_path = output / "archive-receipt.json"
    write_json(receipt_path, {**result, "transfer_status": "pending"}, exclusive=True)
    try:
        manifest = upload_archive(
            archive, **_release(contract["evidence_release"]), work_dir=output / "release-parts"
        )
        write_json(output / "evidence-manifest.json", manifest, exclusive=True)
        manifest_json = _manifest_json(manifest, contract["evidence_release"])
        result["transfer_status"] = "completed"
    except Exception as exc:
        write_json(
            receipt_path, {**result, "transfer_status": "failed", "error_type": type(exc).__name__}
        )
        raise
    write_json(receipt_path, result)
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            for key in (
                "archive_sha256",
                "receipt_sha256",
                "ledger_sha256",
                "continuation_allowed",
            ):
                value = result[key]
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
            stream.write("evidence_manifest_json=" + manifest_json + "\n")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    guard_parser = commands.add_parser("dispatch-guard", help="拒绝同 master 从空账本再次正式派发")
    guard_parser.add_argument("--history", type=Path, required=True)
    guard_parser.add_argument("--master-sha256", required=True)
    guard_parser.add_argument("--run-id", type=int, required=True)
    generate_parser = commands.add_parser("generate")
    for name in ("plan", "bundle-directory", "output"):
        generate_parser.add_argument("--" + name, type=Path, required=True)
    generate_parser.add_argument("--seed-manifest", type=Path, required=True)
    generate_parser.add_argument("--resume-receipt", type=Path)
    generate_parser.add_argument("--through-sequence", type=int)
    freeze_parser = commands.add_parser("freeze-resume", help="离线冻结待 Linux 原生核验的恢复声明")
    for name in (
        "plan",
        "bundle-directory",
        "output",
        "seed-manifest",
        "archive-receipt",
        "history",
        "jobs-directory",
    ):
        freeze_parser.add_argument("--" + name, type=Path, required=True)
    freeze_parser.add_argument("--prefix-length", type=int, required=True)
    review_parser = commands.add_parser("resume-review", help="复核实时 Actions 历史及原生完整前缀")
    review_parser.add_argument("--contract")
    review_parser.add_argument("--history", type=Path, required=True)
    review_parser.add_argument("--jobs-directory", type=Path, required=True)
    review_parser.add_argument("--run-id", type=int, required=True)
    verify_parser = commands.add_parser("resume-verify", help="无模型 Secret 复核首个剩余片")
    verify_parser.add_argument("--contract")
    verify_parser.add_argument("--shard-id", default="")
    verify_parser.add_argument("--mode", choices=("shard", "merge"), required=True)
    for name in ("restore", "execute", "archive", "merge"):
        sub = commands.add_parser(name)
        sub.add_argument("--contract", default=None)
        if name == "restore":
            sub.add_argument("--download-dir", type=Path, required=True)
        if name in {"execute", "archive"}:
            sub.add_argument("--shard-id", required=True)
        if name == "execute":
            sub.add_argument("--probe", type=Path, required=True)
            sub.add_argument("--runner-preparation", type=Path, required=True)
            sub.add_argument("--deadline-epoch", type=float, required=True)
            sub.add_argument("--previous-receipt-sha256", default="")
            sub.add_argument("--previous-ledger-sha256", default="")
        if name == "archive":
            sub.add_argument("--output", type=Path, required=True)
        if name == "merge":
            sub.add_argument("--previous-receipt-sha256", required=True)
            sub.add_argument("--previous-ledger-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "dispatch-guard":
            try:
                guard_study_dispatch(
                    json.loads(args.history.read_text(encoding="utf-8")),
                    args.master_sha256,
                    args.run_id,
                )
            except (OSError, ValueError, TypeError):
                print(
                    json.dumps(
                        {
                            "dispatch_allowed": False,
                            "reason": "history_unconfirmed_or_master_already_dispatched",
                            "explicit_prefix_resume_required": True,
                        }
                    )
                )
                return 2
            print(json.dumps({"dispatch_allowed": True, "master_sha256": args.master_sha256}))
            return 0
        if args.command == "generate":
            generate(
                args.plan,
                args.bundle_directory,
                args.output,
                seed_manifest=args.seed_manifest,
                resume_receipt=args.resume_receipt,
                through_sequence=args.through_sequence,
            )
            return 0
        if args.command == "freeze-resume":
            plan, master, runner = inspect_plan(args.plan, args.bundle_directory)
            study_resume.freeze_resume_receipt(
                args.plan,
                args.bundle_directory,
                args.output,
                prefix_length=args.prefix_length,
                seed_manifest=args.seed_manifest,
                archive_receipt=args.archive_receipt,
                history=args.history,
                jobs_directory=args.jobs_directory,
                plan=plan,
                master=master,
                runner=runner,
            )
            return 0
        text = args.contract or os.environ["SAYACODE_STUDY_CONTRACT"]
        if args.command == "resume-review":
            contract = json.loads(text)
            resume = contract["resume_receipt"]
            jobs = {
                str(run_id): json.loads(
                    (args.jobs_directory / f"{run_id}.json").read_text(encoding="utf-8")
                )
                for run_id in resume["prior_run_ids"]
            }
            study_resume._resume_history(
                resume,
                json.loads(args.history.read_text(encoding="utf-8")),
                jobs,
                current_run_id=args.run_id,
            )
            verify_resume_contract(text)
            print(
                json.dumps(
                    {"native_prefix_verified": True, "prefix_length": resume["prefix_length"]}
                )
            )
            return 0
        if args.command == "resume-verify":
            verify_resume_contract(text, shard_id=args.shard_id, mode=args.mode)
            return 0
        if args.command == "restore":
            contract = json.loads(text)
            root = PurePosixPath(contract["bundle_root"])
            if root.parent != PurePosixPath("/tmp/sayacode-studies") or not LABEL.fullmatch(
                root.name
            ):
                raise ValueError("恢复目标不是固定 Linux study bundle")
            current = (
                subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True)
                .stdout.decode()
                .strip()
            )
            if current != contract["public_source_sha"]:
                raise ValueError("public source SHA 不同")
            manifest = json.loads(os.environ["SAYACODE_EVIDENCE_MANIFEST"])
            _manifest_json(manifest, contract["evidence_release"])
            archive = download_archive(
                manifest, **_release(contract["evidence_release"]), output_dir=args.download_dir
            )
            restore_archive(archive, Path(contract["bundle_root"]), manifest["archive_sha256"])
            load_contract(text)
        elif args.command == "execute":
            value = execute(
                text,
                args.shard_id,
                probe=args.probe,
                runner_preparation=args.runner_preparation,
                deadline=args.deadline_epoch,
                receipt_sha=args.previous_receipt_sha256,
                ledger_sha=args.previous_ledger_sha256,
            )
            return (
                0
                if value["error_type"] is None
                and value.get("native_cli_returncode") == 0
                and value.get("receipt_complete") is True
                else 1
            )
        elif args.command == "archive":
            archive_bundle(text, args.output, shard_id=args.shard_id)
        elif args.command == "merge":
            _, plan, _ = load_contract(text)
            verify_resume_contract(text, mode="merge")
            verify_previous(plan, None, args.previous_receipt_sha256, args.previous_ledger_sha256)
            return merge(text)
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        # 不把底层异常正文、绝对路径或凭据写入 Actions 控制台。
        print(type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
