"""云端资格宿主贯穿冻结与分片；只用离线三加一工件，不运行容器。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_gates import evidence

from sayacode_bench import cli, shards
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from scripts import qualify_cloud

COHORT = {"ImageOS": "ubuntu24", "ImageVersion": "20261019.55.1", "RUNNER_ARCH": "X64"}


@pytest.fixture
def case(tmp_path: Path) -> SimpleNamespace:
    bundle = tmp_path / "bundle"
    inputs = bundle / "inputs"
    inputs.mkdir(parents=True)
    task, gate, probe = evidence()
    task.update(
        benchmark="fixture",
        revision="revision",
        repository="synthetic/repo",
        leakage_group="synthetic-fix",
        agent={"timeout_sec": 3000},
        verifier={"timeout_sec": 3000},
    )
    task["environment"]["build_timeout_sec"] = 1800
    selection, sanity, network = (
        inputs / "selection.json",
        bundle / "qualification/sanity.json",
        inputs / "network.json",
    )
    write_json(selection, {"dev": [task], "holdout": []})
    write_json(sanity, gate)
    write_json(network, probe)
    wheel, requirements, variant, profile = (
        inputs / name
        for name in ("product.whl", "requirements.txt", "baseline.json", "remote.json")
    )
    wheel.write_bytes(b"synthetic frozen wheel")
    requirements.write_bytes(b"synthetic frozen requirements")
    write_json(variant, {"id": "baseline"})
    write_json(
        profile,
        {
            "protocol": "anthropic_messages",
            "model_id": "DeepSeek-V4.1-Flash",
            "base_url": "https://synthetic.invalid",
            "api_key": "synthetic-not-secret",
        },
    )
    args = argparse.Namespace(
        selection=selection,
        sanity=sanity,
        network_probe=network,
        phase="dev",
        variant=[f"baseline={variant}"],
        connection=[f"remote={profile}"],
        repeats=2,
        reported_token_limit=10000,
        seed="fixed-offline",
        wheel=wheel,
        requirements=requirements,
        output=inputs / "master.json",
    )
    return SimpleNamespace(bundle=bundle, inputs=inputs, args=args, gate=gate)


def cloud_gate(case: SimpleNamespace) -> dict[str, Any]:
    plan = qualify_cloud.plan_identity("a" * 40, dict(COHORT))
    write_json(case.inputs / "cloud-plan.json", plan)
    return qualify_cloud.bind_qualification_host(case.bundle, plan)


def make_plan(case: SimpleNamespace, cohort: dict[str, str] | None) -> Path:
    runner, authorization = case.inputs / "runner.json", case.inputs / "authorization.json"
    policy: dict[str, Any] = {"platform": "linux", "architecture": "amd64"}
    if cohort is not None:
        policy["host_cohort"] = cohort
    write_json(runner, policy)
    write_json(
        authorization,
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(case.args.output),
        },
    )
    path = case.bundle / "plan.json"
    shards.freeze_execution_plan(
        case.args.output, runner, authorization, path, bundle_root=case.bundle
    )
    return path


def test_public_gate_metadata_survives_cli_freeze_and_matching_plan(case: SimpleNamespace) -> None:
    gate = cloud_gate(case)
    assert gate["tasks"] == case.gate["tasks"]
    assert gate["passed"] == case.gate["passed"]
    assert gate["qualification_host_cohort"] == COHORT
    assert gate["qualification_host_scope"]["execution_repository"] == "saya-ch/sayacode-bench"
    assert "not identical hardware" in gate["qualification_host_scope"]["host_hardware_boundary"]
    manifest = cli.freeze(case.args)
    assert manifest["qualification_host_cohort"] == COHORT
    assert manifest["qualification_host_scope"] == gate["qualification_host_scope"]
    plan = make_plan(case, dict(COHORT))
    _, restored, _ = shards._load_plan(plan)
    assert restored["qualification_host_cohort"] == COHORT


@pytest.mark.parametrize(
    "cohort", [None, {**COHORT, "ImageVersion": "changed"}, {**COHORT, "RUNNER_ARCH": "ARM64"}]
)
def test_cloud_qualification_cannot_choose_a_different_formal_runner(
    case: SimpleNamespace, cohort: Any
) -> None:
    cloud_gate(case)
    cli.freeze(case.args)
    with pytest.raises(ValueError, match="资格检查完全相同"):
        make_plan(case, cohort)
    assert not (case.bundle / "plan.json").exists()


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"ImageOS": "ubuntu24"},
        {**COHORT, "ImageVersion": " "},
        {**COHORT, "RUNNER_ARCH": "ARM64"},
        {**COHORT, "extra": "ignored"},
    ],
)
def test_invalid_present_cohort_is_not_treated_as_legacy(case: SimpleNamespace, bad: Any) -> None:
    gate = deepcopy(case.gate)
    gate["qualification_host_cohort"] = bad
    write_json(case.args.sanity, gate)
    with pytest.raises(ValueError, match="cohort"):
        cli.freeze(case.args)


def test_existing_noncloud_gate_does_not_invent_a_cohort(case: SimpleNamespace) -> None:
    manifest = cli.freeze(case.args)
    assert "qualification_host_cohort" not in manifest
    shards._load_plan(make_plan(case, None))


@pytest.mark.parametrize("scope", [None, {}, {"unrecognized": "value"}])
def test_present_invalid_public_scope_is_not_ignored(case: SimpleNamespace, scope: Any) -> None:
    gate = cloud_gate(case)
    gate["qualification_host_scope"] = scope
    write_json(case.args.sanity, gate)
    with pytest.raises(ValueError, match="来源或宿主证据边界"):
        cli.freeze(case.args)


def test_interrupted_wrapper_cannot_promote_bare_public_gate(case: SimpleNamespace) -> None:
    cloud_gate(case)
    write_json(case.args.sanity, case.gate)
    with pytest.raises(ValueError, match="cloud-plan"):
        cli.freeze(case.args)


def test_reread_rejects_cohort_drift_even_with_updated_runner_file_hash(
    case: SimpleNamespace,
) -> None:
    cloud_gate(case)
    cli.freeze(case.args)
    path = make_plan(case, dict(COHORT))
    plan = read_json(path)
    runner = Path(plan["runner_policy"]["path"])
    changed = read_json(runner)
    changed["host_cohort"]["ImageVersion"] = "different"
    write_json(runner, changed)
    plan["runner_policy"]["sha256"] = file_sha256(runner)
    write_json(path, plan)
    with pytest.raises(ValueError, match="资格检查完全相同"):
        shards._load_plan(path)


def test_public_rebinding_refuses_conflicting_cohort_and_missing_scope_cannot_be_hidden(
    case: SimpleNamespace,
) -> None:
    gate = cloud_gate(case)
    gate["qualification_host_cohort"]["ImageVersion"] = "wrong"
    write_json(case.args.sanity, gate)
    plan = read_json(case.inputs / "cloud-plan.json")
    with pytest.raises(ValueError, match="冲突"):
        qualify_cloud.bind_qualification_host(case.bundle, plan)
    gate.pop("qualification_host_cohort")
    with pytest.raises(ValueError, match="缺少"):
        shards.qualification_host_cohort(gate)
