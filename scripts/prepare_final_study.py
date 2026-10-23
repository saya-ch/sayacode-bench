"""只装配固定主研究或终端最终阶段，复用原 CLI、原收据与同一预算。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.gates import validate_preflight
from sayacode_bench.locking import validate_candidate_receipt
from sayacode_bench.release_evidence import download_archive, upload_archive
from sayacode_bench.shards import qualification_host_cohort
from sayacode_bench.sources import SOURCES, TaskRecord
from sayacode_bench.study import paid_budget_report, validate_execution_inputs
from scripts.analyze_sensitivity import protocol_identity
from scripts.generate_sharded_workflow import inspect_plan, restore_archive
from scripts.prepare_cloud_runner import require_hosted_runner
from scripts.prepare_primary_study import (
    BUNDLE,
    QUALIFICATION,
    RELEASE,
    ROOT,
    _api,
    _cli,
    _sha,
    verify_primary_qualification,
)
from scripts.qualify_fixtures import control_issues


# 这些函数只校验输入及调用既有 CLI，不计算新评分或调优候选。
def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def review_completed(
    name: str,
    count: int,
    repeats: int,
    configurations: list[str],
    *,
    cohort: dict[str, str],
    output: Path,
    source_sha: str,
) -> tuple[dict[str, Any], Path]:
    """从原收据重归并到临时目录，核对旧完整 final 与累计记录；不改旧文件。"""
    inputs = BUNDLE / "inputs/restart-v2"
    plan_path = BUNDLE / (name + "-v2-plan.json")
    plan, master, runner = inspect_plan(plan_path, BUNDLE)
    validate_execution_inputs(master)
    require(
        runner["public_source_sha"] == source_sha and runner["host_cohort"] == cohort,
        "来源源码或实际宿主 cohort 不一致",
    )
    require(plan["master"]["path"] == str(inputs / (name + ".json")), "阶段 master 路径不一致")
    require(
        len(master["tasks"]) == count
        and master["repeats"] == repeats
        and master["configurations"] == configurations,
        "阶段样本或重复数与原授权不同",
    )
    final = BUNDLE / "merged" / plan["master"]["sha256"] / "final"
    original = read_json(final / "merge-receipt.json")
    require(
        original.get("complete") is True
        and original.get("missing_trials") == 0
        and not original.get("validity_issues"),
        "上一阶段未完整收尾",
    )
    require(original.get("plan_sha256") == file_sha256(plan_path), "归并来源计划不一致")
    receipts = [
        BUNDLE / "shards" / row["shard_id"] / "shard-receipt.json" for row in plan["schedule"]
    ]
    require(all(path.is_file() for path in receipts), "上一阶段缺少完整分片收据")
    review = output / (name + "-review")
    _cli(
        [
            "merge-shards",
            "--plan",
            str(plan_path),
            "--output",
            str(review),
            *[item for path in receipts for item in ("--receipt", str(path))],
        ],
        output / (name + "-review.log"),
    )
    checked = read_json(review / "merge-receipt.json")
    require(
        checked["complete"] is True
        and checked["missing_trials"] == 0
        and not checked["validity_issues"],
        "原始证据复核不完整",
    )
    require(checked["summary"] == original["summary"], "已保存汇总与原证据重验不同")
    for name in ("records.jsonl", "accounting-records.jsonl"):
        require(
            file_sha256(final / name) == file_sha256(review / name),
            "原阶段记录或累计费用与收据链不同",
        )
    require(
        original["records"]
        == {"path": str(final / "records.jsonl"), "sha256": file_sha256(final / "records.jsonl")},
        "原逐次记录身份不一致",
    )
    financial = checked["summary"].get("paid_budget", {})
    require(
        financial.get("evidence_valid") is True
        and financial.get("usage_complete") is True
        and financial.get("stop_reason") is None,
        "费用未知或原预算已停止，不能准备新阶段",
    )
    return master, final


def candidate_configuration(
    candidate_path: Path, dev: dict[str, Any], dev_results: Path
) -> tuple[str, list[str]]:
    """只读取原 SWE 签收，不允许通过阶段参数另选候选。"""
    dev_path = BUNDLE / "inputs/restart-v2/primary-dev.json"
    candidate = read_json(candidate_path)
    require(
        candidate["dev_manifest"] == {"path": str(dev_path), "sha256": file_sha256(dev_path)}
        and candidate["dev_records"]
        == {
            "path": str(dev_results / "records.jsonl"),
            "sha256": file_sha256(dev_results / "records.jsonl"),
        },
        "候选签收不是原完整 SWE 开发来源",
    )
    selected = candidate["selected"]
    require(
        selected in dev["configurations"] and candidate["baseline"] == "baseline",
        "候选身份不匹配",
    )
    return (
        ("validation", ["baseline"])
        if selected == "baseline"
        else ("holdout", ["baseline", selected])
    )


def restore_terminal_qualification(
    target: Path,
    output: Path,
    *,
    artifact_id: int,
    zip_sha: str,
    tar_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """保全已核的 Terminal v9 原归档；恢复到原路径，不覆盖 SWE。"""
    # 完整公开资格 tar 进入同一私有 bundle，后续不依赖三天 artifact 保留期。
    source_sha = "3e03c56f23494399c7093241683acec19cbe125b"
    archive_dir = BUNDLE / "qualifications"
    archive_dir.mkdir(exist_ok=True)
    cached = archive_dir / "terminal-v9.bundle.tar.gz"
    if not cached.exists():
        artifact = _api(f"repos/saya-ch/sayacode-bench/actions/artifacts/{artifact_id}")
        run = _api(f"repos/saya-ch/sayacode-bench/actions/runs/{artifact['workflow_run']['id']}")
        require(
            artifact.get("expired") is False and artifact.get("digest") == "sha256:" + zip_sha,
            "公开资格服务摘要不匹配",
        )
        require(
            run.get("head_sha") == source_sha
            and run.get("run_attempt") == 1
            and run.get("conclusion") == "success"
            and run.get("display_title") == "qualification terminal-v9-host20261012",
            "公开资格来源运行不匹配",
        )
        zipped = output / "terminal-qualification.zip"
        with zipped.open("xb") as stream:
            subprocess.run(
                ["gh", "api", f"repos/saya-ch/sayacode-bench/actions/artifacts/{artifact_id}/zip"],
                stdout=stream,
                check=True,
                timeout=300,
            )
        require(
            _sha(zipped) == zip_sha and zipped.stat().st_size == artifact["size_in_bytes"],
            "原始资格 ZIP 校验失败",
        )
        with zipfile.ZipFile(zipped) as archive:
            names = [name for name in archive.namelist() if name.endswith("bundle.tar.gz")]
            require(len(names) == 1, "资格归档缺少唯一 bundle")
            with archive.open(names[0]) as source, cached.open("xb") as destination:
                shutil.copyfileobj(source, destination)
        write_json(
            archive_dir / "terminal-v9.json",
            {
                "artifact": artifact,
                "run_id": run["id"],
                "source_sha": source_sha,
                "zip_sha256": zip_sha,
                "tar_sha256": tar_sha,
            },
            exclusive=True,
        )
    provenance = read_json(archive_dir / "terminal-v9.json")
    require(
        provenance["artifact"]["id"] == int(artifact_id)
        and provenance["source_sha"] == source_sha
        and provenance["zip_sha256"] == zip_sha
        and provenance["tar_sha256"] == tar_sha,
        "已保留资格归档来源不同",
    )
    restore_archive(cached, target, tar_sha)
    return read_json(target / "qualification/selection.json"), read_json(
        target / "qualification/sanity.json"
    )


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    require_hosted_runner()
    require(
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        == args.source_sha,
        "实际源码提交不一致",
    )
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=ROOT, check=True)
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_sha), "需要原开发冻结的完整源码 SHA")
    stage = args.stage
    require(stage in {"primary_final", "terminal_final"}, "阶段无效")
    temporary = Path(os.environ["RUNNER_TEMP"])
    output = temporary / "evidence/final-prepared"
    output.mkdir(exist_ok=False)
    preparation = read_json(temporary / "evidence/runner-preparation.json")
    probe = read_json(temporary / "evidence/network-probe.json")
    cohort = preparation["runner_image"]
    require(
        preparation.get("passed") is True
        and preparation.get("repository") == RELEASE["repository"]
        and preparation.get("script_sha256")
        == file_sha256(ROOT / "scripts/prepare_cloud_runner.py"),
        "本宿主准备未确认",
    )
    filename = args.seed_manifest_file
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json", filename), "输入必须是安全的单文件名")
    manifest_path = ROOT.parent / "execution/artifacts" / filename
    require(
        not manifest_path.is_symlink()
        and manifest_path.resolve().parent == (ROOT.parent / "execution/artifacts").resolve(),
        "输入来源越界",
    )
    incoming = read_json(manifest_path)
    archive = download_archive(incoming, output_dir=output / "input-download", **RELEASE)
    restore_archive(archive, BUNDLE, incoming["archive_sha256"])
    shared, inputs = BUNDLE / "inputs", BUNDLE / "inputs/restart-v2"
    target_name = "primary-final" if stage == "primary_final" else "terminal-final"
    master_path = inputs / (target_name + ".json")
    plan_path = BUNDLE / (target_name + "-v2-plan.json")
    authorization_path = inputs / (target_name + "-authorization.json")
    require(
        not any(path.exists() for path in (master_path, plan_path, authorization_path)),
        "该阶段已有计划，不得重新冻结或覆盖，应显式恢复原计划",
    )
    scope = read_json(shared / "formal-authorization.json")
    require(
        scope.get("kind") == "user_authorized_formal_evaluation_scope"
        and scope.get("confirmation") == "均同意"
        and scope.get("repository_id") == 1429748203
        and scope.get("private_required") is True,
        "缺少既有正式范围授权",
    )
    require(
        scope.get("actions_free_only") is True
        and scope.get("actions_paid_spending_authorized") is False
        and scope.get("cumulative_model_budget_cny") == "100"
        and scope.get("historical_settlement_sha256")
        == file_sha256(shared / "historical/settlement.json"),
        "免费 Actions 或累计预算授权不一致",
    )
    require(
        read_json(inputs / "analysis-protocol.json") == protocol_identity(),
        "新轮次分析身份与固定源码不同",
    )
    require("api_key" not in read_json(shared / "remote-profile.json"), "公开连接输入不得包含凭据")
    origin = read_json(inputs / "preparation-evidence.json")
    require(
        origin.get("qualification_archive_relative_path")
        == "qualifications/primary-v7.bundle.tar.gz",
        "原开发 seed 未保全固定 SWE 资格归档",
    )
    restore_archive(
        BUNDLE / "qualifications/primary-v7.bundle.tar.gz",
        QUALIFICATION,
        origin["qualification_tar_sha256"],
    )
    selection = read_json(QUALIFICATION / "qualification/selection.json")
    gate = read_json(QUALIFICATION / "qualification/sanity.json")
    verify_primary_qualification(selection, gate, probe, cohort)
    dev, dev_results = review_completed(
        "primary-dev",
        8,
        2,
        ["baseline", "diagnostic", "focused"],
        cohort=cohort,
        output=output,
        source_sha=args.source_sha,
    )
    require(
        dev["phase"] == "dev"
        and dev["tasks"] == selection["dev"]
        and dev["selection_sha256"] == file_sha256(QUALIFICATION / "qualification/selection.json"),
        "开发来源不是原冻结资格选集",
    )
    require(
        dev["paid_budget"]["limit_cny"] == 100
        and dev["paid_budget"]["stop_fraction"] == 0.8
        and dev["paid_budget"]["historical_settlement"]["sha256"]
        == scope["historical_settlement_sha256"],
        "开发阶段原预算不一致",
    )
    candidate_path = inputs / "primary-candidate.json"
    if stage == "primary_final":
        _cli(
            [
                "lock-candidate",
                "--manifest",
                str(inputs / "primary-dev.json"),
                "--records",
                str(dev_results / "records.jsonl"),
                *[
                    item
                    for name in dev["configurations"]
                    for item in ("--variant", f"{name}={shared / (name + '.json')}")
                ],
                "--output",
                str(candidate_path),
            ],
            output / "lock-candidate.log",
        )
    phase, labels = candidate_configuration(candidate_path, dev, dev_results)
    require(
        dev.get("execution_epoch", {}).get("id") == "restart-v2",
        "最终阶段只能使用新轮次完整开发结果",
    )
    validate_execution_inputs(dev)
    prior = [dev_results / "accounting-records.jsonl"]
    qualification = QUALIFICATION
    repeats = 2
    role = []
    if stage == "terminal_final":
        primary, primary_results = review_completed(
            "primary-final", 24, 2, labels, cohort=cohort, output=output, source_sha=args.source_sha
        )
        validate_candidate_receipt(candidate_path, primary)
        require(
            primary["phase"] == phase
            and primary["tasks"] == selection["holdout"]
            and primary["candidate_receipt"]
            == {"path": str(candidate_path), "sha256": file_sha256(candidate_path)},
            "主最终阶段与原候选或资格不同",
        )
        prior.append(primary_results / "accounting-records.jsonl")
        qualification = Path("/tmp/sayacode-studies/terminal-v9-host20261012")
        selection, gate = restore_terminal_qualification(
            qualification,
            output,
            artifact_id=args.terminal_artifact_id,
            zip_sha=args.terminal_zip_sha256,
            tar_sha=args.terminal_tar_sha256,
        )
        tasks = [*selection["dev"], *selection["holdout"]]
        require(
            len(selection["dev"]) == 2
            and len(selection["holdout"]) == 12
            and len({task["task_id"] for task in tasks}) == 14
            and len(gate["tasks"]) == 14,
            "终端资格必须完整覆盖原定十四题",
        )
        require(
            all(
                task["benchmark"] == "terminal-bench-2.1"
                and task["revision"] == SOURCES["terminal-bench-2.1"].revision
                for task in tasks
            ),
            "终端任务不是原冻结版本",
        )
        require(
            qualification_host_cohort(gate) == cohort
            and gate["qualification_host_scope"]["public_source_sha"]
            == "3e03c56f23494399c7093241683acec19cbe125b",
            "终端资格来源或宿主 cohort 不同",
        )
        validate_preflight(
            gate,
            probe,
            benchmark="terminal-bench-2.1",
            revision=SOURCES["terminal-bench-2.1"].revision,
            tasks=tasks,
        )
        checked = {row["task_id"]: row for row in gate["tasks"]}
        for definition in tasks:
            task = TaskRecord(**definition)
            row = checked[task.task_id]
            for name, repeat, record in [
                *(
                    ("oracle", index, record)
                    for index, record in enumerate(row["oracle_trials"], 1)
                ),
                ("nop", 1, row["nop"]),
            ]:
                require(not control_issues(task, record, name, repeat), "终端原生资格原件未确认")
        repeats = 1
        role = [
            "--study-role",
            "terminal_supplement",
            "--primary-dev-manifest",
            str(inputs / "primary-dev.json"),
        ]
    count = (24 if stage == "primary_final" else 12) * repeats * len(labels)
    scope_key = ("primary_final_trials_" if stage == "primary_final" else "terminal_trials_") + (
        "if_baseline" if phase == "validation" else "if_candidate"
    )
    require(
        scope.get(scope_key) == count and scope.get("primary_dev_trials") == 48,
        "下一阶段超出已授权固定规模",
    )
    _cli(
        [
            "freeze",
            "--phase",
            phase,
            "--selection",
            str(qualification / "qualification/selection.json"),
            "--sanity",
            str(qualification / "qualification/sanity.json"),
            "--network-probe",
            str(temporary / "evidence/network-probe.json"),
            "--seed",
            "sayacode-" + target_name + "-20261023-v2",
            "--repeats",
            str(repeats),
            "--reported-token-limit",
            str(dev["reported_token_limit"]),
            *[
                item
                for name in labels
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
            *[item for path in prior for item in ("--prior-records", str(path))],
            "--execution-protocol",
            dev["execution_epoch"]["protocol"]["path"],
            "--analysis-protocol",
            dev["execution_epoch"]["analysis_protocol"]["path"],
            "--installation-preflight",
            dev["execution_epoch"]["installation_preflight"]["path"],
            "--pilot-carry",
            dev["paid_budget"]["pilot_carry"]["path"],
            "--candidate-lock",
            str(candidate_path),
            *role,
            "--output",
            str(master_path),
        ],
        output / "freeze.log",
    )
    master = read_json(master_path)
    expected_budget = {
        **dev["paid_budget"],
        "prior_records": [
            {"path": str(path), "sha256": file_sha256(path)}
            for path in sorted(
                {*prior, *(Path(ref["path"]) for ref in dev["paid_budget"]["prior_records"])}
            )
        ],
    }
    require(
        master["paid_budget"] == expected_budget
        and master["connection_profiles"] == dev["connection_profiles"]
        and master["execution_epoch"] == dev["execution_epoch"],
        "跨阶段预算、价格或模型连接发生变化",
    )
    validate_execution_inputs(master)
    financial = paid_budget_report(master, [])
    require(
        financial["evidence_valid"] is True
        and financial["usage_complete"] is True
        and financial["stop_reason"] is None,
        "累计费用未知或预算已停止",
    )
    write_json(
        authorization_path,
        {
            "authorized": True,
            "phase": phase,
            "master_manifest_sha256": file_sha256(master_path),
            "scope_authorization_sha256": file_sha256(shared / "formal-authorization.json"),
        },
        exclusive=True,
    )
    _cli(
        [
            "plan-shards",
            "--manifest",
            str(master_path),
            "--runner-policy",
            str(inputs / "runner-policy.json"),
            "--authorization",
            str(authorization_path),
            "--bundle-root",
            str(BUNDLE),
            "--output",
            str(plan_path),
        ],
        output / "plan.log",
    )
    require(len(read_json(plan_path)["schedule"]) == count, "最终 schedule 不符合原定数量")
    assembly = {
        "execution_epoch": "restart-v2",
        "stage": stage,
        "model_trials_started": 0,
        "formal_trials_planned": count,
        "master_sha256": file_sha256(master_path),
        "plan_sha256": file_sha256(plan_path),
        "candidate_sha256": file_sha256(candidate_path),
        "source_sha": args.source_sha,
        "input_archive_sha256": incoming["archive_sha256"],
        "workflow_sha256": file_sha256(
            ROOT.parent / "execution/.github/workflows/prepare-final-study.yml"
        ),
        "runner_preparation": preparation,
        "network_probe": probe,
        "paid_budget": financial,
    }
    write_json(inputs / (target_name + "-preparation.json"), assembly, exclusive=True)
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
    parser.add_argument("--seed-manifest-file", required=True)
    parser.add_argument("--stage", choices=["primary_final", "terminal_final"], required=True)
    parser.add_argument("--terminal-artifact-id", type=int)
    parser.add_argument("--terminal-zip-sha256", default="")
    parser.add_argument("--terminal-tar-sha256", default="")
    args = parser.parse_args()
    if args.stage == "terminal_final":
        require(
            type(args.terminal_artifact_id) is int and args.terminal_artifact_id > 0,
            "终端资格工件 ID 无效",
        )
        require(
            all(
                re.fullmatch(r"[0-9a-f]{64}", value)
                for value in (args.terminal_zip_sha256, args.terminal_tar_sha256)
            ),
            "终端资格完整 SHA 缺失",
        )
    elif (
        args.terminal_artifact_id is not None
        or args.terminal_zip_sha256
        or args.terminal_tar_sha256
    ):
        raise ValueError("主研究不接受终端资格参数")
    print(json.dumps(prepare(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
