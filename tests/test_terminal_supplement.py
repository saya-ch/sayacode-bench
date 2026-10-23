"""终端补充的离线来源、恢复和候选约束；不构成真实官方任务成绩。"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from harbor.models.task.config import NetworkMode, TaskConfig
from harbor.models.trial.config import AgentConfig, EnvironmentConfig
from harbor.trial.network_policy import resolve_agent_env_baseline, resolve_agent_phase_policy
from resource_samples import complete_resource_fixture
from test_fixture_qualification import catalog
from test_locking import experiment as experiment

from sayacode_bench import cli
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.locking import lock_candidate, validate_candidate_receipt
from sayacode_bench.publish import export_results
from sayacode_bench.selection import select_tasks
from sayacode_bench.sources import SOURCES
from scripts import qualify_cloud, qualify_fixtures

COHORT = {"ImageOS": "offline-ubuntu", "ImageVersion": "fixed", "RUNNER_ARCH": "X64"}


@pytest.fixture
def terminal_case(experiment: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """以完整合成开发记录验证阶段接线，不伪装成已完成的主研究。"""
    case = experiment
    plan = case["manifest"]
    plan.update(
        benchmark="swe-bench-pro-v2",
        revision=SOURCES["swe-bench-pro-v2"].revision,
        configurations=["baseline", "diagnostic", "focused"],
        baseline="baseline",
        tasks=[
            {
                "benchmark": "swe-bench-pro-v2",
                "revision": SOURCES["swe-bench-pro-v2"].revision,
                "task_id": f"synthetic-dev-{index}",
                "leakage_group": f"repo:synthetic-{index}",
                "repository": "synthetic/repo",
            }
            for index in range(8)
        ],
    )
    variants = {}
    for label in plan["configurations"]:
        path = tmp_path / f"{label}.json"
        write_json(path, {"id": label})
        variants[label] = path
    case["variants"] = variants
    plan["artifacts"]["variants"] = {label: file_sha256(path) for label, path in variants.items()}
    for name, field in (("product.whl", "product_wheel"), ("requirements.txt", "requirements")):
        path = tmp_path / name
        path.write_bytes(b"synthetic offline artifact")
        case[field] = path
        plan["artifacts"][field] = file_sha256(path)
    sample = case["records"][0]
    case["records"] = [
        {
            **deepcopy(sample),
            "task_id": task["task_id"],
            "configuration": label,
            "repeat": repeat,
            "success": label == "diagnostic",
        }
        for task in plan["tasks"]
        for label in plan["configurations"]
        for repeat in (1, 2)
    ]
    complete_resource_fixture(plan, case["records"])
    write_json(case["manifest_path"], plan)
    case["records_path"].write_text(
        "".join(json.dumps(row) + "\n" for row in case["records"]), encoding="utf-8"
    )
    case["final"] = {
        **deepcopy(plan),
        "phase": "holdout",
        "study_role": "terminal_supplement",
        "benchmark": "terminal-bench-2.1",
        "revision": SOURCES["terminal-bench-2.1"].revision,
        "repeats": 1,
        "configurations": ["baseline", "diagnostic"],
        "candidate": "diagnostic",
        "tasks": read_json(qualify_cloud.TERMINAL_SELECTION)["holdout"],
        "primary_dev_manifest": {
            "path": str(case["manifest_path"]),
            "sha256": file_sha256(case["manifest_path"]),
        },
    }
    case["final"]["artifacts"]["variants"].pop("focused")
    return case


def lock(case: dict[str, Any]) -> None:
    lock_candidate(
        case["manifest_path"], case["records_path"], case["variants"], case["receipt_path"]
    )


def test_frozen_terminal_metadata_preserves_original_scope_and_official_network() -> None:
    selection = read_json(qualify_cloud.TERMINAL_SELECTION)
    assert file_sha256(qualify_cloud.TERMINAL_SELECTION) == qualify_cloud.TERMINAL_SHA
    assert selection["seed"] == "sayacode-tb-20261022-scope-v1"
    assert selection["study_role"] == "terminal_supplement"
    assert selection["eligible_count"] == 45
    assert len(selection["dev"]) == 2 and len(selection["holdout"]) == 12
    assert selection["rules"]["max_memory_mb"] == 4096
    assert selection["rules"]["max_agent_timeout_sec"] == 1800
    assert set(selection["rules"]["categories"]) == {
        "software-engineering",
        "debugging",
        "system-administration",
        "file-operations",
        "data-processing",
        "security",
    }
    for task in selection["dev"] + selection["holdout"]:
        assert task["benchmark"] == "terminal-bench-2.1"
        assert task["revision"] == SOURCES[task["benchmark"]].revision
        assert task["environment"]["allow_internet"] is True
        config = TaskConfig.model_validate(
            {name: task[name] for name in ("agent", "verifier", "environment")}
        )
        baseline = resolve_agent_env_baseline(config, EnvironmentConfig())
        policy = resolve_agent_phase_policy(config, AgentConfig(name="nop"), baseline)
        assert policy.network_mode == NetworkMode.PUBLIC
        assert "instruction" not in task and "solution" not in task


def test_public_terminal_qualification_reuses_fixed_controls_and_cannot_resume_as_primary(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "terminal"
    plan = qualify_cloud.initialize(bundle, "a" * 40, COHORT, "terminal")
    assert plan["oracle_repeats"] == 3 and plan["nop_repeats"] == 1
    assert plan["max_candidates"] == 64 and plan["model_requests_planned"] == 0
    assert plan["source_license"] == "Apache-2.0"
    assert "official_public_Apache-2.0_task_snapshot" in plan["public_artifact_scope"]
    assert qualify_cloud.initialize(bundle, "a" * 40, COHORT, "terminal") == plan
    with pytest.raises(ValueError, match="续批"):
        qualify_cloud.initialize(bundle, "a" * 40, COHORT, "primary")
    packed = qualify_cloud.pack_bundle(bundle, tmp_path / "archive")
    assert packed["study_kind"] == "terminal" and packed["source_license"] == "Apache-2.0"
    primary = qualify_cloud.plan_identity("a" * 40, COHORT, "primary")
    assert primary["source_license"] == "MIT"
    assert primary["initial_selection_sha256"] == qualify_cloud.INITIAL_SHA
    with pytest.raises(ValueError):
        qualify_cloud.study_definition("arbitrary")


def test_workflow_exposes_fixed_terminal_choice_and_passes_it_to_run_and_archive() -> None:
    workflow = yaml.safe_load(qualify_cloud.WORKFLOW.read_text(encoding="utf-8"))
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["study_kind"]["options"] == ["primary", "terminal"]
    assert (
        qualify_cloud.WORKFLOW.read_text(encoding="utf-8").count('--study-kind "$STUDY_KIND"') == 2
    )


def test_primary_dev_r2_receipt_drives_terminal_r1_without_retuning(
    terminal_case: dict[str, Any],
) -> None:
    lock(terminal_case)
    receipt = validate_candidate_receipt(terminal_case["receipt_path"], terminal_case["final"])
    assert receipt["selected"] == "diagnostic"
    assert terminal_case["final"]["repeats"] == 1


def test_qualification_replacement_keeps_declared_terminal_role() -> None:
    tasks = catalog(18, "terminal-bench-2.1")
    initial = select_tasks(tasks, dev_count=2, holdout_count=12, seed="offline-fixed").public_dict()
    initial["study_role"] = "terminal_supplement"
    rejected = {initial["holdout"][0]["leakage_group"]}
    selected = qualify_fixtures.select_again(tasks, initial, rejected)
    assert selected["study_role"] == "terminal_supplement"
    assert selected["seed"] == initial["seed"]
    assert selected["catalog_sha256"] == initial["catalog_sha256"]
    assert len(selected["dev"]) == 2 and len(selected["holdout"]) == 12
    assert not rejected.intersection(
        task["leakage_group"] for task in selected["dev"] + selected["holdout"]
    )
    assert any(row["reason"] == "fixture_qualification_failed" for row in selected["exclusions"])


def test_primary_baseline_selection_allows_only_terminal_single_group_validation(
    terminal_case: dict[str, Any],
) -> None:
    case = terminal_case
    for row in case["records"]:
        row["success"] = row["configuration"] == "baseline"
    case["records_path"].write_text(
        "".join(json.dumps(row) + "\n" for row in case["records"]), encoding="utf-8"
    )
    final = case["final"]
    final.update(phase="validation", candidate=None, configurations=["baseline"])
    final["artifacts"]["variants"].pop("diagnostic")
    lock(case)
    assert validate_candidate_receipt(case["receipt_path"], final)["selected"] == "baseline"
    final["phase"] = "holdout"
    with pytest.raises(ValueError, match="基线"):
        validate_candidate_receipt(case["receipt_path"], final)


@pytest.mark.parametrize(
    "change", ["terminal-dev", "another-primary", "r2-final", "eleven", "variant"]
)
def test_terminal_role_rejects_retuning_source_scale_or_variant_changes(
    terminal_case: dict[str, Any],
    change: str,
    tmp_path: Path,
) -> None:
    case, final = terminal_case, terminal_case["final"]
    if change == "terminal-dev":
        case["manifest"]["benchmark"] = "terminal-bench-2.1"
        write_json(case["manifest_path"], case["manifest"])
        final["primary_dev_manifest"]["sha256"] = file_sha256(case["manifest_path"])
    elif change == "another-primary":
        alternate = tmp_path / "different-dev.json"
        write_json(alternate, case["manifest"])
        final["primary_dev_manifest"]["path"] = str(alternate)
    elif change == "r2-final":
        final["repeats"] = 2
    elif change == "eleven":
        final["tasks"].pop()
    elif change == "variant":
        final["artifacts"]["variants"]["diagnostic"] = "f" * 64
    lock(case)
    with pytest.raises(ValueError):
        validate_candidate_receipt(case["receipt_path"], final)


def test_generic_locking_entry_remains_available_for_other_studies(
    terminal_case: dict[str, Any],
) -> None:
    case = terminal_case
    final = case["final"]
    final.pop("study_role")
    final.pop("primary_dev_manifest")
    final["repeats"] = 3
    lock(case)
    validate_candidate_receipt(case["receipt_path"], final)


def test_terminal_cli_refuses_dev_before_loading_credentials(tmp_path: Path) -> None:
    args = argparse.Namespace(
        selection=qualify_cloud.TERMINAL_SELECTION,
        study_role="terminal_supplement",
        phase="dev",
        primary_dev_manifest=tmp_path / "unused",
    )
    with pytest.raises(ValueError, match="不得在终端题上重新调参"):
        cli.freeze(args)


@pytest.mark.parametrize("explicit", [False, True])
def test_declared_terminal_selection_cannot_silently_fall_back_to_generic(explicit: bool) -> None:
    args = argparse.Namespace(selection=qualify_cloud.TERMINAL_SELECTION)
    if explicit:
        args.study_role = "generic"
    with pytest.raises(ValueError, match="研究角色"):
        cli.freeze(args)


def test_terminal_public_manifest_retains_role_and_primary_hash_without_private_path(
    terminal_case: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "terminal-private.json"
    records = tmp_path / "terminal-empty.jsonl"
    write_json(manifest, terminal_case["final"])
    records.write_text("", encoding="utf-8")
    output = tmp_path / "public"
    export_results(manifest, records, output)
    public = read_json(output / "manifest.json")
    assert public["study_role"] == "terminal_supplement"
    assert public["primary_dev_manifest"] == {"sha256": file_sha256(terminal_case["manifest_path"])}
    assert str(terminal_case["manifest_path"]) not in json.dumps(public)
    assert read_json(output / "analysis.json")["final_result_eligible"] is False


def test_terminal_cli_freezes_explicit_primary_identity_and_same_selected_variants(
    terminal_case: dict[str, Any],
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    case = terminal_case
    lock(case)
    gate, probe, profile = (
        tmp_path / name for name in ("sanity.json", "network.json", "profile.json")
    )
    write_json(
        gate,
        {
            "tasks": [
                {
                    "task_id": task["task_id"],
                    "oracle": {
                        "runtime_identity": {
                            "available": True,
                            "image_id": "synthetic",
                            "architecture": "amd64",
                            "os": "linux",
                        }
                    },
                }
                for task in case["final"]["tasks"]
            ]
        },
    )
    write_json(probe, {})
    write_json(profile, {"protocol": "anthropic_messages", "model_id": "DeepSeek-V4.1-Flash"})
    # 本测试只验证冻结入口接线；真实 preflight 的完整性由既有门禁测试负责。
    monkeypatch.setattr(cli, "validate_preflight", lambda *_args, **_kwargs: None)
    args = argparse.Namespace(
        selection=qualify_cloud.TERMINAL_SELECTION,
        study_role="terminal_supplement",
        primary_dev_manifest=case["manifest_path"],
        phase="holdout",
        repeats=1,
        candidate_lock=case["receipt_path"],
        sanity=gate,
        network_probe=probe,
        variant=[f"{label}={case['variants'][label]}" for label in ("baseline", "diagnostic")],
        connection=[f"offline={profile}"],
        wheel=case["product_wheel"],
        requirements=case["requirements"],
        seed="fixed-terminal-order",
        reported_token_limit=1000,
        output=tmp_path / "terminal-master.json",
    )
    frozen = cli.freeze(args)
    assert frozen["study_role"] == "terminal_supplement"
    assert frozen["primary_dev_manifest"]["sha256"] == file_sha256(case["manifest_path"])
    assert frozen["candidate_receipt"]["sha256"] == file_sha256(case["receipt_path"])
    validate_candidate_receipt(case["receipt_path"], frozen)
