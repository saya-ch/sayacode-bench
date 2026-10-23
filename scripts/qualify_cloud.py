"""有限数量的无模型云端资格控制；每批最多一个任务，不自动派发下一批。"""

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
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.network import docker
from sayacode_bench.shards import qualification_host_cohort
from scripts.diagnose_fixtures import pin_image
from scripts.generate_sharded_workflow import restore_archive
from scripts.prepare_cloud_runner import require_hosted_runner
from scripts.qualify_fixtures import digest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/qualify-study.yml"
INITIAL_SELECTION = ROOT / "studies/primary-selection-v1.json"
INITIAL_SHA = "39e62eb0c5aa51595cf1455f2a51c1579b57e3a61e35b3d4a8078a3b84a207c9"
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
STUDY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}\Z")
HOST_FIELDS = ("ImageOS", "ImageVersion", "RUNNER_ARCH")
MIN_DISK = 12 * 1024**3
PUBLIC_REPOSITORY = "saya-ch/sayacode-bench"
PUBLIC_ARTIFACT_SCOPE = (
    "fixed_public_selection",
    "official_public_MIT_task_snapshot",
    "oracle_nop_native_logs",
    "requested_and_actual_container_resources",
    "public_actions_host_metadata",
)
HOST_BOUNDARY = "public standard host 4 CPU/16 GiB versus private 2 CPU/8 GiB; not identical hardware; official container CPU/RAM/swap remain unchanged and measured"


def require_public_repository(metadata: Path) -> None:
    require_hosted_runner(controls_only=True)
    project = read_json(metadata)
    if (
        project.get("full_name") != PUBLIC_REPOSITORY
        or project.get("private") is not False
        or project.get("visibility") != "public"
    ):
        raise ValueError("公开资格材料只允许指定公开仓库；拒绝模型私有仓库")


def archive_sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def bundle_root(study_id: str) -> Path:
    if not STUDY.fullmatch(study_id):
        raise ValueError("study ID 格式无效")
    return Path("/tmp/sayacode-studies") / study_id


def cohort(image_os: str, image_version: str) -> dict[str, str]:
    if not image_os.strip() or not image_version.strip():
        raise ValueError("必须明确冻结宿主 ImageOS 与 ImageVersion")
    return {"ImageOS": image_os, "ImageVersion": image_version, "RUNNER_ARCH": "X64"}


def guard_first_batch(history: Any, study_id: str, run_number: int) -> None:
    """只读原生 Actions 历史防止忘传续批；不声称能发现被人工删除的历史。"""
    if (
        not isinstance(history, list)
        or not history
        or type(run_number) is not int
        or run_number <= 0
    ):
        raise ValueError("Actions 历史未确认")
    rows: list[dict[str, Any]] = []
    counts = []
    for page in history:
        if (
            not isinstance(page, dict)
            or type(page.get("total_count")) is not int
            or not isinstance(page.get("workflow_runs"), list)
        ):
            raise ValueError("Actions 历史分页结构未确认")
        counts.append(page["total_count"])
        rows.extend(page["workflow_runs"])
    if any(
        not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0
        for row in rows
    ):
        raise ValueError("Actions 原生 run 列表未确认")
    if counts != [len(rows)] * len(counts) or len({row.get("id") for row in rows}) != len(rows):
        raise ValueError("Actions 历史分页不完整或不一致")
    title = f"qualification {study_id}"
    current = False
    for row in rows:
        if type(row.get("run_number")) is not int or not isinstance(row.get("display_title"), str):
            raise ValueError("Actions 原生 run 身份未确认")
        current |= row["run_number"] == run_number and row["display_title"] == title
        if row["run_number"] < run_number and row["display_title"] == title:
            raise ValueError("该 study 已有历史，必须显式恢复完整 artifact，不得再次启动首批")
    if not current:
        raise ValueError("Actions 历史缺少当前原生 run")


def verify_source(source_sha: str, workflow: Path) -> None:
    """只接受固定公开源码与逐字节相同的私有模板，不读取模型配置。"""
    if not COMMIT.fullmatch(source_sha):
        raise ValueError("公开源码必须是完整小写提交 SHA")
    current = (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True)
        .stdout.decode()
        .strip()
    )
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    if (
        current != source_sha
        or file_sha256(workflow) != file_sha256(WORKFLOW)
        or file_sha256(INITIAL_SELECTION) != INITIAL_SHA
    ):
        raise ValueError("源码、资格模板或初始公开选择身份不同")


def plan_identity(source_sha: str, expected_cohort: dict[str, str]) -> dict[str, Any]:
    initial = read_json(INITIAL_SELECTION)
    return {
        "schema_version": 1,
        "phase": "cloud_fixture_qualification",
        "execution_repository": PUBLIC_REPOSITORY,
        "public_artifact_scope": list(PUBLIC_ARTIFACT_SCOPE),
        "host_hardware_boundary": HOST_BOUNDARY,
        "public_source_sha": source_sha,
        "implementation": implementation_identity(),
        "initial_selection_sha256": INITIAL_SHA,
        "seed": initial["seed"],
        "oracle_repeats": 3,
        "nop_repeats": 1,
        "max_candidates": 64,
        "host_cohort": expected_cohort,
        "source_files": {
            str(path.relative_to(ROOT)): file_sha256(path)
            for path in (
                Path(__file__),
                ROOT / "scripts/qualify_fixtures.py",
                ROOT / "scripts/prepare_cloud_runner.py",
                ROOT / "scripts/generate_sharded_workflow.py",
                ROOT / "scripts/diagnose_fixtures.py",
                WORKFLOW,
            )
        },
        "model_requests_planned": 0,
        "formal_execution_authorized": False,
        "host_cohort_scope": list(HOST_FIELDS),
        "host_cohort_exclusions": [
            "physical_cpu_identity",
            "kernel_identity",
            "provider_model_immutability",
        ],
    }


def initialize(bundle: Path, source_sha: str, expected_cohort: dict[str, str]) -> dict[str, Any]:
    """续批只恢复同一计划；N 可变，固定规则和初选不可变。"""
    expected = plan_identity(source_sha, expected_cohort)
    expected["bundle_root"] = str(bundle.resolve())
    path = bundle / "inputs/cloud-plan.json"
    if bundle.exists():
        if (
            read_json(path) != expected
            or file_sha256(bundle / "inputs/initial-selection.json") != INITIAL_SHA
        ):
            raise ValueError("续批 source、实现、seed、cohort 或固定三加一规则变化")
    else:
        bundle.mkdir(parents=True, exist_ok=False)
        write_json(path, expected, exclusive=True)
        shutil.copyfile(INITIAL_SELECTION, bundle / "inputs/initial-selection.json")
    return expected


def preparation_issues(preparation: dict[str, Any], expected: dict[str, str]) -> bool:
    return (
        preparation.get("passed") is not True
        or preparation.get("script_sha256") != file_sha256(ROOT / "scripts/prepare_cloud_runner.py")
        or preparation.get("runner_image") != expected
        or preparation.get("repository") != PUBLIC_REPOSITORY
        or preparation.get("controls_only") is not True
        or preparation.get("role") != "public_official_controls_host_preparation"
    )


def next_task(bundle: Path) -> dict[str, Any] | None:
    selection = bundle / "qualification/selection.json"
    current = read_json(
        selection if selection.exists() else bundle / "inputs/initial-selection.json"
    )
    for task in [*current["dev"], *current["holdout"]]:
        key = digest({"benchmark": task["benchmark"], "task_id": task["task_id"]})[:20]
        path = bundle / "qualification/qualifications" / key / "qualification.json"
        if not path.exists() or read_json(path).get("complete") is not True:
            return dict(task)
    return None


def task_complete(bundle: Path, task: dict[str, Any]) -> bool:
    key = digest({"benchmark": task["benchmark"], "task_id": task["task_id"]})[:20]
    path = bundle / "qualification/qualifications" / key / "qualification.json"
    return path.is_file() and read_json(path).get("complete") is True


def control_reserve(task: dict[str, Any]) -> int:
    values = [
        task[section][field]
        for section, field in (
            ("environment", "build_timeout_sec"),
            ("agent", "timeout_sec"),
            ("verifier", "timeout_sec"),
        )
    ]
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or value <= 0
        for value in values
    ):
        raise ValueError("缺少有限的官方控制墙钟预算")
    return int(math.ceil(sum(values) + 900))


async def prepare_task_image(bundle: Path, task: dict[str, Any]) -> dict[str, Any]:
    """首个控制记录真实 tag 身份；续批从该真实 RepoDigest 恢复，不编造 digest。"""
    original = task["environment"]["docker_image"]
    path = (
        bundle / "state/images" / (hashlib.sha256(task["task_id"].encode()).hexdigest() + ".json")
    )
    if path.is_file():
        saved: dict[str, Any] = read_json(path)
        if saved["task_id"] != task["task_id"] or saved["original_image_reference"] != original:
            raise ValueError("已有镜像来源不是当前官方任务")
        actual = await pin_image(
            {"immutable_image": saved["repo_digest"], "original_image_reference": original}
        )
        if (
            actual["expected_image_id"] != saved["image_id"]
            or actual["os"] != saved["os"]
            or actual["architecture"] != saved["architecture"]
        ):
            raise ValueError("续批固定镜像实际身份不同")
        return saved
    await docker("pull", original, timeout=600)
    image = json.loads(await docker("image", "inspect", original))[0]
    repository = original.rsplit(":", 1)[0]
    matches = [
        value for value in image.get("RepoDigests", []) if value.startswith(repository + "@sha256:")
    ]
    if len(matches) != 1 or image.get("Os") != "linux" or image.get("Architecture") != "amd64":
        raise ValueError("首次官方 tag 没有唯一真实 RepoDigest 或平台不同")
    result = {
        "task_id": task["task_id"],
        "original_image_reference": original,
        "repo_digest": matches[0],
        "image_id": image["Id"],
        "os": image["Os"],
        "architecture": image["Architecture"],
    }
    write_json(path, result, exclusive=True)
    return result


def _attempt_count(bundle: Path) -> int:
    return sum(1 for _ in (bundle / "qualification/qualifications").glob("*/*.attempt.json"))


def call_qualifier(bundle: Path, log: Path, deadline: float) -> int:
    command = [
        sys.executable,
        "-m",
        "scripts.qualify_fixtures",
        "--selection",
        str(bundle / "inputs/initial-selection.json"),
        "--cache",
        str(bundle / "cache"),
        "--output",
        str(bundle / "qualification"),
        "--oracle-repeats",
        "3",
        "--max-candidates",
        "64",
        "--max-new-controls",
        "1",
    ]
    with log.open("wb") as stream:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=max(1, deadline - time.time()),
            check=False,
        )
    return result.returncode


def bind_qualification_host(bundle: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """原生控制结果保持原样，只补上本次固定的公开宿主来源边界。"""
    path = bundle / "qualification/sanity.json"
    gate = read_json(path)
    expected = {
        "qualification_host_cohort": dict(plan["host_cohort"]),
        "qualification_host_scope": {
            key: plan[key]
            for key in (
                "execution_repository",
                "public_source_sha",
                "host_cohort_scope",
                "host_cohort_exclusions",
                "host_hardware_boundary",
            )
        }
        | {"cloud_plan_sha256": file_sha256(bundle / "inputs/cloud-plan.json")},
    }
    qualification_host_cohort(expected)
    for key, value in expected.items():
        if key in gate and gate[key] != value:
            raise ValueError("已有资格门禁的宿主来源与冻结计划冲突")
    gate.update(expected)
    write_json(path, gate)
    return dict(gate)


def run_batch(
    bundle: Path,
    plan: dict[str, Any],
    preparation: Path,
    probe: Path,
    *,
    max_controls: int,
    deadline: float,
) -> dict[str, Any]:
    """有限行政批次：最多 N 次既有 CLI，且在一个任务三加一边界停止。"""
    if type(max_controls) is not int or not 1 <= max_controls <= 256 or not math.isfinite(deadline):
        raise ValueError("显式控制上限须为 1..256，截止时间须有限")
    batches = bundle / "batches"
    number = len(list(batches.glob("batch-*"))) + 1
    directory = batches / f"batch-{number:04d}"
    directory.mkdir(parents=True, exist_ok=False)
    status: dict[str, Any] = {
        "schema_version": 1,
        "batch": number,
        "max_new_controls": max_controls,
        "new_controls": 0,
        "complete": False,
        "passed": False,
        "continuation_allowed": False,
        "reason": None,
        "error_type": None,
        "model_requests": 0,
        "formal_execution_authorized": False,
        "plan_sha256": file_sha256(bundle / "inputs/cloud-plan.json"),
    }
    write_json(directory / "attempt.json", {**status, "deadline_epoch": deadline}, exclusive=True)
    before = _attempt_count(bundle)
    try:
        prepared = read_json(preparation)
        write_json(directory / "runner-preparation.json", prepared, exclusive=True)
        if preparation_issues(prepared, plan["host_cohort"]):
            raise ValueError("宿主镜像 cohort 或准备脚本漂移")
        observed = read_json(probe)
        write_json(directory / "network-probe.json", observed, exclusive=True)
        if (
            observed.get("passed") is not True
            or observed.get("cleanup_confirmed") is not True
            or observed.get("source_sha256", {}).get("network.py")
            != implementation_identity()["network.py"]
        ):
            raise ValueError("当前网络探针或清理未确认")
        task = next_task(bundle)
        if task is None:
            sanity = bind_qualification_host(bundle, plan)
            status.update(
                complete=sanity.get("complete") is True,
                passed=sanity.get("passed") is True,
                reason="already_complete"
                if sanity.get("passed") is True
                else "qualification_unconfirmed",
            )
            return status
        status["task_id"] = task["task_id"]
        reserve = control_reserve(task)
        if time.time() + reserve > deadline:
            status.update(reason="time_guard", continuation_allowed=True)
            return status
        if shutil.disk_usage(bundle).free < MIN_DISK:
            status["reason"] = "insufficient_disk_headroom"
            return status
        write_json(
            directory / "image.json", asyncio.run(prepare_task_image(bundle, task)), exclusive=True
        )
        for index in range(max_controls):
            if time.time() + reserve > deadline:
                status.update(reason="time_guard", continuation_allowed=True)
                break
            if shutil.disk_usage(bundle).free < MIN_DISK:
                status["reason"] = "insufficient_disk_headroom"
                break
            rc = call_qualifier(bundle, directory / f"control-{index + 1}.log", deadline)
            status["native_cli_returncode"] = rc
            status["new_controls"] = _attempt_count(bundle) - before
            if rc not in {0, 1}:
                raise ValueError("资格 CLI 异常退出")
            sanity = bind_qualification_host(bundle, plan)
            reason = sanity.get("qualification", {}).get("reason")
            if sanity.get("complete") is True and sanity.get("passed") is True:
                status.update(complete=True, passed=True, reason=None)
                break
            if reason != "control_batch_limit_reached":
                status["reason"] = reason or "qualification_execution_unconfirmed"
                break
            if task_complete(bundle, task):
                status.update(reason="task_boundary", continuation_allowed=True)
                break
            if status["new_controls"] != index + 1:
                raise ValueError("本批没有独立推进一个控制；未知原生现场不得重跑")
        else:
            status.update(reason="control_batch_limit_reached", continuation_allowed=True)
    except Exception as exc:
        status["error_type"] = type(exc).__name__
        status["continuation_allowed"] = False
        status["reason"] = status["reason"] or "qualification_execution_unconfirmed"
    finally:
        status["new_controls"] = _attempt_count(bundle) - before
        write_json(directory / "batch.json", status, exclusive=True)
    return status


def pack_bundle(bundle: Path, output: Path, *, entry_report: Path | None = None) -> dict[str, Any]:
    """仅归档固定公开输入产生的资格材料；不复制私有 wheel/profile/账单。"""
    if (
        read_json(bundle / "inputs/cloud-plan.json").get("execution_repository")
        != PUBLIC_REPOSITORY
    ):
        raise ValueError("拒绝将私有或模型 bundle 当作公开资格工件上传")
    if output.resolve().is_relative_to(bundle.resolve()):
        raise ValueError("tar 必须在 bundle 外部")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz", dereference=False) as stream:
        for path in sorted(bundle.iterdir()):
            stream.add(path, arcname=path.name)
    batches = sorted((bundle / "batches").glob("batch-*/batch.json"))
    latest = read_json(batches[-1]) if batches else {}
    if entry_report is not None:
        # 本次入口失败不能继承前序批次的可继续状态；旧批次事实仍在完整 tar 中。
        latest = read_json(entry_report) if entry_report.is_file() else {}
    result = {
        "schema_version": 1,
        "archive_sha256": archive_sha(archive),
        "archive_bytes": archive.stat().st_size,
        "plan_sha256": file_sha256(bundle / "inputs/cloud-plan.json"),
        "complete": latest.get("complete") is True,
        "passed": latest.get("passed") is True,
        "continuation_allowed": latest.get("continuation_allowed") is True,
        "entry_error_type": latest.get("error_type"),
        "entry_report_sha256": file_sha256(entry_report)
        if entry_report is not None and entry_report.is_file()
        else None,
        "model_requests": 0,
        "formal_execution_authorized": False,
        "selection_path": str(bundle / "qualification/selection.json"),
        "sanity_path": str(bundle / "qualification/sanity.json"),
        "retention_days": 3,
        "public_artifact_scope": list(PUBLIC_ARTIFACT_SCOPE),
        "host_hardware_boundary": HOST_BOUNDARY,
        "storage_note": "公开标准 runner 资格控制不消耗私有 2000 分钟；公开工件三天保留，不保证平台永远免费，不自动删除。",
        "cloud_artifact_deletion_performed": False,
    }
    write_json(output / "bundle-manifest.json", result, exclusive=True)
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(f"archive_sha256={result['archive_sha256']}\n")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "archive"):
        sub = commands.add_parser(name)
        sub.add_argument("--study-id", required=True)
        sub.add_argument("--entry-report", type=Path)
        sub.add_argument("--repository-metadata", type=Path, required=True)
        if name == "run":
            sub.add_argument("--source-sha", required=True)
            sub.add_argument("--workflow", type=Path, required=True)
            sub.add_argument("--image-os", required=True)
            sub.add_argument("--image-version", required=True)
            sub.add_argument("--runner-preparation", type=Path, required=True)
            sub.add_argument("--probe", type=Path, required=True)
            sub.add_argument("--deadline-epoch", type=float, required=True)
            sub.add_argument("--max-new-controls", type=int, default=4)
            sub.add_argument("--resume-archive", type=Path)
            sub.add_argument("--resume-sha256")
            sub.add_argument("--first-batch-history", type=Path)
            sub.add_argument("--run-number", type=int)
        else:
            sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entry: dict[str, Any] | None = None
    owned_report = False
    try:
        require_public_repository(args.repository_metadata)
        bundle = bundle_root(args.study_id)
        if args.command == "archive":
            pack_bundle(bundle, args.output, entry_report=args.entry_report)
            return 0
        entry = {
            "schema_version": 1,
            "study_id": args.study_id,
            "public_source_sha": args.source_sha,
            "resume_archive_sha256": args.resume_sha256,
            "max_new_controls": args.max_new_controls,
            "complete": False,
            "passed": False,
            "continuation_allowed": False,
            "error_type": None,
            "model_requests": 0,
            "formal_execution_authorized": False,
            "exit_code": None,
            "first_batch_history_confirmed": False,
            "remote_first_batch_deduplication": "native Actions history by study ID; manually deleted runs are not detectable",
        }
        if args.entry_report:
            write_json(args.entry_report, entry, exclusive=True)
            owned_report = True
        verify_source(args.source_sha, args.workflow)
        expected = cohort(args.image_os, args.image_version)
        if args.resume_archive:
            if not args.resume_sha256 or not SHA.fullmatch(args.resume_sha256):
                raise ValueError("续批必须明确原 tar SHA256")
            restore_archive(args.resume_archive, bundle, args.resume_sha256)
        elif args.resume_sha256 or bundle.exists():
            raise ValueError("全新批次不能覆盖已有 bundle；续批必须显式恢复")
        else:
            if args.first_batch_history is None or args.run_number is None:
                raise ValueError("首批必须核验原生 Actions 历史，续批必须传原 artifact")
            history = json.loads(args.first_batch_history.read_text(encoding="utf-8"))
            guard_first_batch(history, args.study_id, args.run_number)
            entry["first_batch_history_confirmed"] = True
        plan = initialize(bundle, args.source_sha, expected)
        status = run_batch(
            bundle,
            plan,
            args.runner_preparation,
            args.probe,
            max_controls=args.max_new_controls,
            deadline=args.deadline_epoch,
        )
        entry.update(status)
        print(
            json.dumps(
                {
                    key: status[key]
                    for key in (
                        "batch",
                        "complete",
                        "passed",
                        "reason",
                        "error_type",
                        "model_requests",
                    )
                },
                ensure_ascii=False,
            )
        )
        result = (
            0
            if status["error_type"] is None and (status["passed"] or status["continuation_allowed"])
            else 1
        )
        entry["exit_code"] = result
        return result
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        if entry is not None:
            entry.update(error_type=type(exc).__name__, exit_code=2, continuation_allowed=False)
        print(type(exc).__name__)
        return 2
    finally:
        if owned_report and args.entry_report and entry is not None:
            write_json(args.entry_report, entry)


if __name__ == "__main__":
    raise SystemExit(main())
