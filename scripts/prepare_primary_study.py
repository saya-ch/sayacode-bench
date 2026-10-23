"""在私有 Linux runner 冻结已授权的主开发阶段；只装配输入，不运行模型。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.gates import validate_preflight
from sayacode_bench.release_evidence import download_archive, upload_archive
from sayacode_bench.shards import qualification_host_cohort
from sayacode_bench.sources import SOURCES, TaskRecord
from sayacode_bench.study import paid_budget_report, validate_statistical_continuity
from scripts.analyze_sensitivity import protocol_identity
from scripts.generate_sharded_workflow import restore_archive
from scripts.prepare_cloud_runner import require_hosted_runner
from scripts.qualify_fixtures import control_issues

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "saya-ch/sayacode-bench-runs"
PUBLIC = "saya-ch/sayacode-bench"
QUALIFICATION = Path("/tmp/sayacode-studies/primary-v7-host20261012")
BUNDLE = Path("/tmp/sayacode-studies/deepseek-v41-20261023")
QUALIFICATION_SOURCE = "5fcc3ce48fa98cd65c98ea5f74c1b36d43c42c0e"
RELEASE = {
    "repository": PRIVATE,
    "release_id": 420920737,
    "release_tag": "research-evidence-20261022",
}


def _api(endpoint: str) -> dict[str, Any]:
    response = subprocess.run(["gh", "api", endpoint], capture_output=True, check=True, timeout=60)
    return dict(json.loads(response.stdout))


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _cli(arguments: list[str], output: Path) -> None:
    environment = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "SAYACODE_STUDY_CONNECTION_KEYS_JSON"):
        environment.pop(key, None)
    with output.open("xb") as log:
        subprocess.run(
            [sys.executable, "-m", "sayacode_bench.cli", *arguments],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )


def private_seed_manifest(path: Path) -> dict[str, Any]:
    """新 seed 只能来自已签收的私有仓库 artifacts 单文件。"""
    directory = ROOT.parent / "execution/artifacts"
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json", path.name)
        or path.is_symlink()
        or path.resolve(strict=True).parent != directory.resolve(strict=True)
    ):
        raise ValueError("新 seed manifest 必须是私有 artifacts 内的安全单文件")
    return dict(read_json(path))


def verify_primary_qualification(
    selection: dict[str, Any],
    gate: dict[str, Any],
    probe: dict[str, Any],
    cohort: dict[str, str],
) -> None:
    """重开全部三十二题的三加一原件；只读已有证据，不创建 Job。"""
    dev, holdout = selection.get("dev"), selection.get("holdout")
    if (
        not isinstance(dev, list)
        or len(dev) != 8
        or not isinstance(holdout, list)
        or len(holdout) != 24
        or gate.get("complete") is not True
        or gate.get("passed") is not True
        or qualification_host_cohort(gate) != cohort
        or gate.get("qualification_host_scope", {}).get("public_source_sha") != QUALIFICATION_SOURCE
    ):
        raise ValueError("必须取得完整原定三十二题资格，且实际宿主 cohort 相同")
    tasks = [*dev, *holdout]
    source = SOURCES["swe-bench-pro-v2"]
    if any(
        not isinstance(task, dict)
        or not isinstance(task.get("task_id"), str)
        or not task["task_id"]
        or task.get("benchmark") != "swe-bench-pro-v2"
        or task.get("revision") != source.revision
        for task in tasks
    ):
        raise ValueError("主研究任务必须来自已冻结的 SWE V2 数据版本")
    task_ids = {task["task_id"] for task in tasks}
    checked = gate.get("tasks")
    if (
        len(task_ids) != 32
        or not isinstance(checked, list)
        or len(checked) != 32
        or any(not isinstance(row, dict) for row in checked)
        or {row.get("task_id") for row in checked} != task_ids
    ):
        raise ValueError("资格原件必须恰好覆盖开发与最终验收的三十二个唯一任务")
    validate_preflight(
        gate, probe, benchmark="swe-bench-pro-v2", revision=source.revision, tasks=tasks
    )
    indexed = {row["task_id"]: row for row in checked}
    for definition in tasks:
        task = TaskRecord(**definition)
        row = indexed[task.task_id]
        controls = [
            *(("oracle", index, trial) for index, trial in enumerate(row["oracle_trials"], 1)),
            ("nop", 1, row["nop"]),
        ]
        for name, repeat, record in controls:
            if control_issues(task, record, name, repeat):
                raise ValueError(f"原生资格原件未确认：{task.task_id} / {name}-{repeat}")


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """以完整先导包为保全基线，仅追加新轮次输入；不读取三天临时资格入口。"""
    from sayacode_bench.study import validate_execution_inputs

    require_hosted_runner()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise ValueError("需要明确的源码提交")
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT, check=True)
    if current != args.source_sha:
        raise ValueError("准备源码与冻结输入不同")
    repository = _api(f"repos/{PRIVATE}")
    if repository.get("id") != 1429748203 or repository.get("private") is not True:
        raise ValueError("指定执行仓库的私有身份不符")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = args.output.resolve()
    if not output.is_relative_to(temporary) or output == temporary:
        raise ValueError("准备证据只能写入本 job 临时目录")
    output.mkdir(parents=True, exist_ok=False)
    preparation = read_json(args.preparation)
    cohort = preparation.get("runner_image")
    if (
        preparation.get("passed") is not True
        or preparation.get("repository") != PRIVATE
        or preparation.get("script_sha256") != file_sha256(ROOT / "scripts/prepare_cloud_runner.py")
    ):
        raise ValueError("当前宿主准备未确认")
    incoming = private_seed_manifest(args.input_manifest)
    seed = download_archive(incoming, output_dir=output / "input-download", **RELEASE)
    restore_archive(seed, BUNDLE, incoming["archive_sha256"])
    preserved = {
        path.relative_to(BUNDLE).as_posix(): file_sha256(path)
        for path in BUNDLE.rglob("*")
        if path.is_file()
    }
    shared, inputs = BUNDLE / "inputs", BUNDLE / "inputs/restart-v2"
    scope = read_json(shared / "formal-authorization.json")
    if (
        scope.get("kind") != "user_authorized_formal_evaluation_scope"
        or scope.get("confirmation") != "均同意"
        or scope.get("repository_id") != repository["id"]
        or scope.get("private_required") is not True
        or scope.get("actions_free_only") is not True
        or scope.get("actions_paid_spending_authorized") is not False
        or scope.get("primary_dev_trials") != 48
        or scope.get("cumulative_model_budget_cny") != "100"
        or scope.get("historical_settlement_sha256")
        != file_sha256(shared / "historical/settlement.json")
        or "api_key" in read_json(shared / "remote-profile.json")
    ):
        raise ValueError("用户授权、历史核销或无凭据输入未确认")
    origin = read_json(shared / "preparation-evidence.json")
    if (
        origin.get("qualification_archive_relative_path")
        != "qualifications/primary-v7.bundle.tar.gz"
    ):
        raise ValueError("先导包缺少原始完整资格归档")
    restore_archive(
        BUNDLE / "qualifications/primary-v7.bundle.tar.gz",
        QUALIFICATION,
        origin["qualification_tar_sha256"],
    )
    gate = read_json(QUALIFICATION / "qualification/sanity.json")
    selection = read_json(QUALIFICATION / "qualification/selection.json")
    verify_primary_qualification(selection, gate, read_json(args.probe), cohort)
    analysis_identity = protocol_identity()
    validate_statistical_continuity(read_json(shared / "analysis-protocol.json"), analysis_identity)
    for name in ("baseline", "diagnostic", "focused"):
        if file_sha256(shared / (name + ".json")) != file_sha256(
            ROOT / "studies" / (name + ".json")
        ):
            raise ValueError("先导之后不能更改三个预声明算法配置")
    inputs.mkdir(exist_ok=True)
    write_json(inputs / "analysis-protocol.json", analysis_identity, exclusive=True)
    protocol = inputs / "execution-protocol.json"
    source_protocol = ROOT / "studies/execution-protocol-v13.json"
    if protocol.exists():
        if protocol.read_bytes() != source_protocol.read_bytes():
            raise ValueError("新执行协议与预先装配输入不同")
    else:
        shutil.copyfile(source_protocol, protocol)
    master = inputs / "primary-dev.json"
    plan_path = BUNDLE / "primary-dev-v2-plan.json"
    authorization = inputs / "primary-dev-authorization.json"
    if any(
        path.exists() for path in (master, plan_path, authorization, inputs / "runner-policy.json")
    ):
        raise ValueError("新轮次已有冻结计划，必须恢复原计划而非重新冻结")
    _cli(
        [
            "freeze",
            "--phase",
            "dev",
            "--selection",
            str(QUALIFICATION / "qualification/selection.json"),
            "--sanity",
            str(QUALIFICATION / "qualification/sanity.json"),
            "--network-probe",
            str(args.probe),
            "--seed",
            "sayacode-primary-dev-20261023-v1",
            "--repeats",
            "2",
            "--reported-token-limit",
            "1000000000",
            *[
                item
                for name in ("baseline", "diagnostic", "focused")
                for item in ("--variant", f"{name}={shared / (name + '.json')}")
            ],
            "--connection",
            f"remote={shared / 'remote-profile.json'}",
            "--wheel",
            str(shared / "sayacode-3.2.4-py3-none-any.whl"),
            "--requirements",
            str(shared / "product-requirements.txt"),
            "--paid-limit-cny",
            "100",
            "--paid-stop-fraction",
            "0.8",
            "--paid-price-snapshot",
            str(shared / "price.json"),
            "--paid-endpoint",
            "remote",
            "--historical-settlement",
            str(shared / "historical/settlement.json"),
            "--execution-protocol",
            str(protocol),
            "--analysis-protocol",
            str(inputs / "analysis-protocol.json"),
            "--installation-preflight",
            str(BUNDLE / "installations/restart-v2/preflight.json"),
            "--pilot-carry",
            str(inputs / "pilot-carry.json"),
            "--output",
            str(master),
        ],
        output / "freeze.log",
    )
    value = read_json(master)
    validate_execution_inputs(value)
    if (
        value["artifacts"]["product_wheel"]
        != "7892afcd50bd0ee786ed3ea5ba73015af32da11cd3eeff5474ce7e64d039dffe"
        or value["artifacts"]["requirements"]
        != "9eab06fb395d7b9bb84e14bfea83b79b4ab66d904c941c3b1606d39ed9712073"
    ):
        raise ValueError("新轮次生产 wheel 或依赖发生变化")
    financial = paid_budget_report(value, [])
    if (
        financial["evidence_valid"] is not True
        or financial["usage_complete"] is not True
        or financial["stop_reason"] is not None
        or financial["budget_consumed_cny"] != 0.95304296
    ):
        raise ValueError("先导三条费用和历史核销未完整、恰好一次延续")
    write_json(
        inputs / "runner-policy.json",
        {
            "platform": "linux",
            "architecture": "amd64",
            "job_timeout_seconds": 21600,
            "public_source_sha": args.source_sha,
            "executor_workflow_sha256": file_sha256(ROOT / ".github/workflows/run-study-shard.yml"),
            "evidence_release": RELEASE,
            "host_cohort": cohort,
        },
        exclusive=True,
    )
    write_json(
        authorization,
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(master),
            "scope_authorization_sha256": file_sha256(shared / "formal-authorization.json"),
            "pilot_carry": value["paid_budget"]["pilot_carry"],
        },
        exclusive=True,
    )
    _cli(
        [
            "plan-shards",
            "--manifest",
            str(master),
            "--runner-policy",
            str(inputs / "runner-policy.json"),
            "--authorization",
            str(authorization),
            "--bundle-root",
            str(BUNDLE),
            "--output",
            str(plan_path),
        ],
        output / "plan.log",
    )
    if len(read_json(plan_path)["schedule"]) != 48:
        raise ValueError("新开发 schedule 必须保持完整四十八次")
    if any(
        not (BUNDLE / name).is_file() or file_sha256(BUNDLE / name) != digest
        for name, digest in preserved.items()
    ):
        raise ValueError("新轮次装配改写了先导或预检原件")
    assembly = {
        "execution_epoch": "restart-v2",
        "phase": "dev",
        "formal_trials_planned": 48,
        "new_epoch_model_trials_started": 0,
        "pilot_trials_preserved": 4,
        "input_members_preserved": len(preserved),
        "input_inventory_sha256": hashlib.sha256(
            json.dumps(preserved, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "master_sha256": file_sha256(master),
        "plan_sha256": file_sha256(plan_path),
        "source_sha": args.source_sha,
        "bundle_root": str(BUNDLE),
        "paid_budget": financial,
        "input_archive_sha256": incoming["archive_sha256"],
        "qualification_tar_sha256": origin["qualification_tar_sha256"],
        "qualification_archive_relative_path": origin["qualification_archive_relative_path"],
        "runner_preparation": preparation,
        "network_probe": read_json(args.probe),
        "script_sha256": file_sha256(Path(__file__)),
    }
    write_json(inputs / "preparation-evidence.json", assembly, exclusive=True)
    write_json(output / "prepared-study.json", assembly, exclusive=True)
    prepared = output / "prepared-bundle.tar.gz"
    with tarfile.open(prepared, "w:gz", dereference=False) as stream:
        for path in sorted(BUNDLE.iterdir()):
            stream.add(path, arcname=path.name)
    uploaded = upload_archive(prepared, work_dir=output / "upload", **RELEASE)
    write_json(output / "evidence-manifest.json", uploaded, exclusive=True)
    return {**assembly, "archive_sha256": uploaded["archive_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    for name in ("input-manifest", "preparation", "probe", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
