"""离线验证私有云端校准的付费、工件和运行边界；不请求模型或 Docker。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from sayacode_bench.sources import SOURCES, SourceSnapshot, tree_digest
from scripts import calibrate_cloud as cloud

ROOT = Path(__file__).resolve().parents[1]


def usage(identity: str, **updates: Any) -> dict[str, Any]:
    return {
        "endpoint": "remote",
        "input_tokens": 100,
        "output_tokens": 10,
        "usage_complete": True,
        "source_job": identity,
        "request_sha256": hashlib.sha256(identity.encode()).hexdigest(),
        "usage": {
            "model_calls": 1,
            "reported_calls": 1,
            "missing_usage_calls": 0,
            "damaged_audit_lines": 0,
        },
        **updates,
    }


def save_records(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def coverage(path: Path, ledger: Path, *, new_budget: bool = False) -> None:
    write_json(
        path,
        {
            "records_sha256": file_sha256(ledger),
            "coverage_confirmed": True,
            "unresolved_in_scope_observations": [],
            "budget_scope": "new_user_authorized_budget"
            if new_budget
            else "all_known_paid_activity",
            "authorization_reference": "offline-test-explicit-user-authorization",
            "budget_start": "2026-10-23T00:00:00Z",
            "historical_observations": [
                {"id": key, "disposition": "prebudget_cost_unknown" if new_budget else "included"}
                for key in sorted(cloud.KNOWN_PAID_PROBES)
            ],
        },
    )


@pytest.fixture
def experiment(tmp_path: Path, monkeypatch: Any) -> Any:
    root = tmp_path / "bench"
    studies = root / "studies"
    studies.mkdir(parents=True)
    source = tmp_path / "cache/snapshot"
    spec = SOURCES["swe-bench-pro-v2"]
    rows = []
    for task_id, _ in cloud.FIXTURES.values():
        task = source / spec.tasks_path / task_id
        task.mkdir(parents=True)
        (task / "task.toml").write_text('version="1.0"\n', encoding="utf-8")
        (task / "instruction.md").write_text("Calibration task.\n", encoding="utf-8")
        rows.append(
            {
                "benchmark": spec.name,
                "revision": spec.revision,
                "task_id": task_id,
                "instruction_sha256": file_sha256(task / "instruction.md"),
                "config_sha256": file_sha256(task / "task.toml"),
                "task_tree_sha256": tree_digest(task),
                "agent": {"timeout_sec": 3000},
                "verifier": {"timeout_sec": 3000},
                "environment": {
                    "cpus": 1,
                    "memory_mb": 4096,
                    "build_timeout_sec": 1800,
                    "docker_image": f"{cloud.IMAGE_REPOSITORY}:{task_id}",
                },
            }
        )
    write_json(
        studies / "calibration.json",
        {"phase": "calibration", "revision": spec.revision, "tasks": rows},
    )
    write_json(studies / "baseline.json", {"id": "baseline", "team_enabled": True})
    prices = studies / "prices"
    prices.mkdir()
    price_name = "siliconflow-deepseek-v4.1-flash-20261022.json"
    (prices / price_name).write_bytes((ROOT / "studies/prices" / price_name).read_bytes())
    monkeypatch.setattr(cloud, "fetch_source", lambda *args: SourceSnapshot(spec, source, "a", 0))
    monkeypatch.setattr(
        cloud.shutil, "disk_usage", lambda *args: SimpleNamespace(free=100 * 1024**3)
    )
    runtime = {
        "available": True,
        "image_id": "sha256:" + "a" * 64,
        "architecture": "amd64",
        "os": "linux",
        "requested": {"cpus": 1, "memory_mb": 4096},
        "docker_limits": {
            "Memory": 4 * 1024**3,
            "MemorySwap": 8 * 1024**3,
            "NanoCpus": 1000000000,
            "CpuPeriod": 0,
            "CpuQuota": 0,
        },
        "cgroup_v2": {
            "cpu.max": "100000 100000",
            "memory.max": "4294967296",
            "memory.swap.max": "4294967296",
        },
        "storage_hard_limit_supported": False,
    }
    probe = tmp_path / "probe.json"
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {"network.py": implementation_identity()["network.py"]},
        },
    )
    prior = tmp_path / "prior.jsonl"
    save_records(
        prior,
        [
            usage(f"historical-{index}", historical_observation_id=key)
            for index, key in enumerate(sorted(cloud.KNOWN_PAID_PROBES))
        ],
    )
    receipt = tmp_path / "prior.receipt.json"
    coverage(receipt, prior)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = artifacts / "product.whl"
    wheel.write_bytes(b"wheel")
    requirements = artifacts / "requirements.txt"
    requirements.write_text("dependency==1\n", encoding="utf-8")
    frozen = {
        "source": {"public_source_sha": "a" * 40},
        "host": {"kernel": "fixture"},
        "artifacts": {
            "wheel": str(wheel),
            "identity": {"production_wheel_sha256": file_sha256(wheel)},
        },
    }
    args = argparse.Namespace(
        root=root,
        fixture="qutebrowser",
        cache=tmp_path / "cache",
        output=tmp_path / "model-qute",
        controls=tmp_path / "controls-qute",
        probe=probe,
        requirements=requirements,
        private_home=tmp_path / "private",
        deadline_epoch=time.time() + 6 * 3600,
        prior_records=[prior],
        prior_ledger_receipt=receipt,
        cloud_prior_records=[],
        cloud_prior_report=None,
    )
    calls: list[dict[str, Any]] = []

    async def fake_resources() -> dict[str, list[str]]:
        return {"containers": [], "networks": [], "volumes": []}

    async def fake_run(manifest: Path, output: Path, *unused: Any) -> dict[str, Any]:
        config = read_json(manifest)
        calls.append(config)
        record = usage(
            str(output / "jobs/source"),
            task_id=config["tasks"][0]["task_id"],
            configuration="baseline",
            repeat=1,
            canonical_model=cloud.CANONICAL_MODEL,
            status="completed",
            record_complete=True,
            verified=True,
            replay_reward=0,
            success=False,
            runtime_comparison={
                "same_image": True,
                "same_platform": True,
                "same_resources": True,
            },
            runtime_identity=copy.deepcopy(runtime),
            replay_runtime_identity=copy.deepcopy(runtime),
        )
        save_records(output / "records.jsonl", [record])
        return {}

    monkeypatch.setattr(cloud, "resources", fake_resources)
    monkeypatch.setattr(cloud, "run_phase", fake_run)
    monkeypatch.setenv("SAYACODE_BENCH_MODEL_API_KEY", "offline-not-a-real-key")
    bundle = SimpleNamespace(
        root=root,
        args=args,
        runtime=runtime,
        rows=rows,
        frozen=frozen,
        calls=calls,
        prior=prior,
        receipt=receipt,
        fake_run=fake_run,
    )
    _controls(bundle, args.fixture, args.controls)
    return bundle


def _controls(bundle: Any, fixture: str, output: Path) -> None:
    row = next(row for row in bundle.rows if row["task_id"] == cloud.FIXTURES[fixture][0])
    records = []
    for index, (agent, repeat) in enumerate(
        (("oracle", 1), ("oracle", 2), ("oracle", 3), ("nop", 1))
    ):
        records.append(
            {
                "task_id": row["task_id"],
                "configuration": agent,
                "repeat": repeat,
                "status": "completed",
                "record_complete": True,
                "verified": True,
                "original_reward": int(agent == "oracle"),
                "success": agent == "oracle",
                "runtime_identity": bundle.runtime,
                "request_sha256": hashlib.sha256(f"request{index}".encode()).hexdigest(),
                "raw_trial_result": {"sha256": hashlib.sha256(f"raw{index}".encode()).hexdigest()},
                "runtime": {"sha256": "a" * 64},
            }
        )
    write_json(
        output / "sanity.json",
        {
            "benchmark": "swe-bench-pro-v2",
            "revision": cloud.REVISION,
            "complete": True,
            "passed": True,
            "tasks": [
                {
                    **row,
                    "passed": True,
                    "oracle_repeats": 3,
                    "oracle_trials": records[:3],
                    "oracle": records[0],
                    "nop": records[3],
                }
            ],
        },
    )
    write_json(output / "cleanup.json", {"cleanup_confirmed": True})


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": True},
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": False, "visibility": "public"},
        {"full_name": "someone/other", "private": True, "visibility": "private"},
    ],
)
def test_public_unknown_or_other_repository_rejected(metadata: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        cloud.require_private(metadata)


@pytest.mark.parametrize("reference", ["main", "v1", "a" * 39, "A" * 40, "a" * 40 + ";exit"])
def test_mutable_or_invalid_source_reference_rejected(tmp_path: Path, reference: str) -> None:
    with pytest.raises(ValueError, match="完整"):
        cloud.source_identity(tmp_path, reference, tmp_path / "workflow")


def test_original_requirements_required_before_build(tmp_path: Path, monkeypatch: Any) -> None:
    root = tmp_path / "bench"
    reproduction = root / "reproduction"
    reproduction.mkdir(parents=True)
    archive = reproduction / "product-baseline-source.zip"
    archive.write_bytes(b"archive")
    write_json(
        reproduction / "identity.json",
        {"source_archive_sha256": file_sha256(archive), "requirements_sha256": "a" * 64},
    )
    monkeypatch.setattr(cloud.subprocess, "run", lambda *args, **kwargs: pytest.fail("不得构建"))
    with pytest.raises(cloud.ArtifactGateError, match="missing_original"):
        cloud.build_baseline(root, tmp_path / "artifacts", tmp_path / "missing")
    wrong = tmp_path / "wrong.txt"
    wrong.write_text("重新导出的替代文件", encoding="utf-8")
    with pytest.raises(ValueError, match="requirements"):
        cloud.build_baseline(root, tmp_path / "artifacts", wrong)


def test_wheel_rebuilt_from_archive_and_exact_bytes_required(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "bench"
    reproduction = root / "reproduction"
    reproduction.mkdir(parents=True)
    archive = reproduction / "product-baseline-source.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("pyproject.toml", "[project]\nname='fixture'\n")
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"exact dependencies\n")
    expected = b"exact original wheel"
    write_json(
        reproduction / "identity.json",
        {
            "source_archive_sha256": file_sha256(archive),
            "requirements_sha256": file_sha256(requirements),
            "production_wheel_sha256": hashlib.sha256(expected).hexdigest(),
        },
    )
    calls = []

    def build(command: list[str], **kwargs: Any) -> None:
        calls.append(command)
        (Path(command[4]) / "sayacode-3.2.4-py3-none-any.whl").write_bytes(expected)

    monkeypatch.setattr(cloud.subprocess, "run", build)
    artifacts = tmp_path / "artifacts"
    built = cloud.build_baseline(root, artifacts, requirements)
    assert file_sha256(Path(built["wheel"])) == hashlib.sha256(expected).hexdigest()
    assert len(calls) == 1 and calls[0][:4] == ["uv", "build", "--wheel", "--out-dir"]
    Path(built["wheel"]).write_bytes(b"different")
    with pytest.raises(ValueError, match="wheel"):
        cloud.build_baseline(root, artifacts, requirements)
    assert len(calls) == 1


@pytest.mark.parametrize("changed_payload", [False, True])
def test_explicit_original_is_selected_and_rebuild_only_diagnoses(
    tmp_path: Path, monkeypatch: Any, changed_payload: bool
) -> None:
    root = tmp_path / "bench"
    reproduction = root / "reproduction"
    reproduction.mkdir(parents=True)
    archive = reproduction / "product-baseline-source.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("pyproject.toml", "[project]\nname='fixture'\n")
    original = tmp_path / "product-baseline.whl"
    rebuilt_input = tmp_path / "linux-build.whl"
    for path, system, payload in (
        (original, 0, b"frozen payload"),
        (rebuilt_input, 3, b"changed payload" if changed_payload else b"frozen payload"),
    ):
        with zipfile.ZipFile(path, "w") as stream:
            entry = zipfile.ZipInfo("sayacode/__init__.py", date_time=(2020, 2, 2, 0, 0, 0))
            entry.create_system = system
            entry.external_attr = 0o644 << 16
            stream.writestr(entry, payload)
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"exact dependencies\n")
    write_json(
        reproduction / "identity.json",
        {
            "source_archive_sha256": file_sha256(archive),
            "requirements_sha256": file_sha256(requirements),
            "production_wheel_sha256": file_sha256(original),
        },
    )

    def build(command: list[str], **kwargs: Any) -> None:
        (Path(command[4]) / "sayacode-3.2.4-py3-none-any.whl").write_bytes(
            rebuilt_input.read_bytes()
        )

    monkeypatch.setattr(cloud.subprocess, "run", build)
    artifacts = tmp_path / "artifacts"
    if changed_payload:
        with pytest.raises(cloud.ArtifactGateError, match="wheel_rebuild_difference_rejected"):
            cloud.build_baseline(root, artifacts, requirements, original)
        assert read_json(artifacts / "rebuild-diagnostic.json")["allowed"] is False
    else:
        selected = cloud.build_baseline(root, artifacts, requirements, original)
        assert selected["wheel_selection"] == "explicit_original"
        assert Path(selected["wheel"]).name == "sayacode-3.2.4-py3-none-any.whl"
        assert file_sha256(Path(selected["wheel"])) == file_sha256(original)
        assert file_sha256(Path(selected["wheel"])) != file_sha256(rebuilt_input)
    evidence = tmp_path / "evidence"
    cloud.archive_rebuild_diagnostic(artifacts, evidence)
    assert file_sha256(evidence / "rebuild/sayacode-3.2.4-py3-none-any.whl") == file_sha256(
        rebuilt_input
    )
    assert (evidence / "rebuild/rebuild-diagnostic.json").is_file()


def test_wrong_explicit_original_does_not_trigger_build_or_fallback(
    tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "bench"
    reproduction = root / "reproduction"
    reproduction.mkdir(parents=True)
    archive = reproduction / "product-baseline-source.zip"
    archive.write_bytes(b"known source")
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"known requirements")
    original = tmp_path / "product-baseline.whl"
    original.write_bytes(b"different wheel")
    write_json(
        reproduction / "identity.json",
        {
            "source_archive_sha256": file_sha256(archive),
            "requirements_sha256": file_sha256(requirements),
            "production_wheel_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        cloud.subprocess, "run", lambda *args, **kwargs: pytest.fail("不得构建替代包")
    )
    with pytest.raises(cloud.ArtifactGateError, match="original_wheel_hash_mismatch"):
        cloud.build_baseline(root, tmp_path / "artifacts", requirements, original)


def test_ledger_missing_unconfirmed_hash_changed_and_unknown_usage(experiment: Any) -> None:
    e = experiment
    assert cloud.prior_ledger_reason([]) == "missing_prior_paid_records"
    assert cloud.prior_ledger_reason([e.prior]) == "missing_prior_ledger_receipt"
    receipt = read_json(e.receipt)
    receipt["coverage_confirmed"] = False
    write_json(e.receipt, receipt)
    assert cloud.prior_ledger_reason([e.prior], e.receipt) == "prior_ledger_coverage_unconfirmed"
    coverage(e.receipt, e.prior)
    save_records(e.prior, [usage("unknown", usage_complete=False)])
    assert cloud.prior_ledger_reason([e.prior], e.receipt) == "prior_ledger_identity_changed"
    rows = [
        usage(str(index), historical_observation_id=key, usage_complete=False)
        for index, key in enumerate(sorted(cloud.KNOWN_PAID_PROBES))
    ]
    save_records(e.prior, rows)
    coverage(e.receipt, e.prior)
    assert cloud.prior_ledger_reason([e.prior], e.receipt) == "paid_usage_incomplete"


def test_new_budget_requires_explicit_scope_authorization(experiment: Any) -> None:
    e = experiment
    save_records(e.prior, [])
    assert cloud.prior_ledger_reason([e.prior]) == "missing_prior_ledger_receipt"
    coverage(e.receipt, e.prior, new_budget=True)
    assert cloud.prior_ledger_reason([e.prior], e.receipt) is None
    value = read_json(e.receipt)
    value["authorization_reference"] = ""
    write_json(e.receipt, value)
    assert cloud.prior_ledger_reason([e.prior], e.receipt) == "new_budget_scope_not_authorized"


@pytest.mark.parametrize("mistake", ["local", "duplicate"])
def test_known_paid_observations_cannot_be_misclassified_or_duplicated(
    experiment: Any, mistake: str
) -> None:
    e = experiment
    rows = cloud.read_records([e.prior])
    if mistake == "local":
        rows[0]["endpoint"] = "local"
    else:
        rows.append(copy.deepcopy(rows[0]))
    save_records(e.prior, rows)
    coverage(e.receipt, e.prior)
    assert cloud.prior_ledger_reason([e.prior], e.receipt) == "known_paid_observations_missing"


async def test_zero_reward_does_not_retry_or_skip_second_task(experiment: Any) -> None:
    e = experiment
    first = await cloud.calibrate(e.args, e.frozen)
    assert first["reward"] == 0 and first["continue_allowed"] is True
    second = argparse.Namespace(**vars(e.args))
    second.fixture = "ansible"
    second.output = e.args.output.parent / "model-ansible"
    second.private_home = e.args.output.parent / "private-ansible"
    second.controls = e.args.output.parent / "controls-ansible"
    _controls(e, "ansible", second.controls)
    second.cloud_prior_records = [e.args.output / "run/records.jsonl"]
    second.cloud_prior_report = e.args.output / "calibration.json"
    report = await cloud.calibrate(second, e.frozen)
    assert report["reward"] == 0 and report["execution_confirmed"] is True
    assert len(e.calls) == 2
    assert all(call["repeats"] == 1 and call["configurations"] == ["baseline"] for call in e.calls)
    assert e.calls[1]["paid_budget"]["limit_cny"] == 100
    assert len(e.calls[1]["paid_budget"]["prior_records"]) == 2
    assert report["cloud_paid_usage"]["unique_records"] == 2
    for path in second.output.rglob("*.json"):
        assert "offline-not-a-real-key" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("missing", "missing_prior_paid_records"),
        ("coverage", "prior_ledger_coverage_unconfirmed"),
        ("time", "insufficient_job_time"),
        ("disk", "insufficient_disk_headroom"),
    ],
)
async def test_known_policy_stops_before_model_and_keeps_reason(
    experiment: Any, monkeypatch: Any, condition: str, reason: str
) -> None:
    e = experiment
    if condition == "missing":
        e.args.prior_records = []
    elif condition == "coverage":
        value = read_json(e.receipt)
        value["coverage_confirmed"] = False
        write_json(e.receipt, value)
    elif condition == "time":
        e.args.deadline_epoch = time.time() + 100
    else:
        monkeypatch.setattr(cloud.shutil, "disk_usage", lambda *args: SimpleNamespace(free=1))
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["model_started"] is False and report["reason"] == reason
    assert not e.calls and not e.args.private_home.exists()


@pytest.mark.parametrize("failure", ["inventory", "cleanup"])
async def test_docker_observation_failure_removes_profile_preserves_usage(
    experiment: Any, monkeypatch: Any, failure: str
) -> None:
    e = experiment

    async def fail(*args: Any) -> Any:
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(cloud, "resources" if failure == "inventory" else "cleanup_evidence", fail)
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["continue_allowed"] is False
    assert not (e.args.private_home / "remote.json").exists()
    assert (e.args.output / "calibration.json").is_file()
    if failure == "cleanup":
        assert (e.args.output / "run/records.jsonl").is_file()
        assert report["cloud_paid_usage"]["paid_model_calls"] == 1


async def test_replay_resource_difference_blocks_continuation(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment

    async def different(*args: Any) -> dict[str, Any]:
        await e.fake_run(*args)
        path = args[1] / "records.jsonl"
        record = cloud.read_records([path])[0]
        record["replay_runtime_identity"]["docker_limits"]["Memory"] = 1
        save_records(path, [record])
        return {}

    monkeypatch.setattr(cloud, "run_phase", different)
    assert (await cloud.calibrate(e.args, e.frozen))["continue_allowed"] is False


async def test_existing_private_credentials_are_preserved(experiment: Any) -> None:
    e = experiment
    e.args.private_home.mkdir()
    original = e.args.private_home / "remote.json"
    original.write_text("existing unrelated credential", encoding="utf-8")
    with pytest.raises(FileExistsError):
        await cloud.calibrate(e.args, e.frozen)
    assert original.read_text(encoding="utf-8") == "existing unrelated credential"
    assert not e.calls


async def test_generated_gateway_credential_is_removed(experiment: Any, monkeypatch: Any) -> None:
    e = experiment
    gateway = e.args.private_home / "runs/run/remote-gateway.json"

    async def with_gateway(*args: Any) -> dict[str, Any]:
        gateway.parent.mkdir(parents=True)
        gateway.write_text("offline-not-a-real-key", encoding="utf-8")
        return await e.fake_run(*args)

    monkeypatch.setattr(cloud, "run_phase", with_gateway)
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["execution_confirmed"] is True
    assert not gateway.exists() and not (e.args.private_home / "remote.json").exists()


async def test_saved_resource_flags_cannot_hide_missing_native_limits(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment

    async def missing_limit(*args: Any) -> dict[str, Any]:
        await e.fake_run(*args)
        path = args[1] / "records.jsonl"
        record = cloud.read_records([path])[0]
        record["replay_runtime_identity"]["cgroup_v2"].pop("memory.max")
        assert record["runtime_comparison"]["same_resources"] is True
        save_records(path, [record])
        return {}

    monkeypatch.setattr(cloud, "run_phase", missing_limit)
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["continue_allowed"] is False
    assert report["cloud_paid_usage"]["paid_model_calls"] == 1


async def test_controls_run_fixed_four_even_after_first_bad_score(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment
    calls = []
    records = read_json(e.args.controls / "sanity.json")["tasks"][0]
    fixed = copy.deepcopy([*records["oracle_trials"], records["nop"]])

    async def native(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((kwargs["configuration"], kwargs["repeat"]))
        result = fixed[len(calls) - 1]
        if len(calls) == 1:
            result.update(original_reward=0, success=False)
        return result

    async def fake_docker(*args: str, **kwargs: Any) -> str:
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                [
                    {
                        "Id": e.runtime["image_id"],
                        "RepoDigests": [
                            f"{cloud.IMAGE_REPOSITORY}@{cloud.FIXTURES['qutebrowser'][1]}"
                        ],
                    }
                ]
            )
        return ""

    monkeypatch.setattr(cloud, "run_official_trial", native)
    monkeypatch.setattr(cloud, "docker", fake_docker)
    passed = await cloud.controls(
        e.root, "qutebrowser", e.args.cache, e.args.probe, e.args.output.parent / "new-controls"
    )
    assert passed is False
    assert calls == [("oracle", 1), ("oracle", 2), ("oracle", 3), ("nop", 1)]


def test_workflow_private_guard_frozen_source_and_safe_defaults() -> None:
    text = (ROOT / ".github/workflows/cloud-calibration.yml").read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["execute_models"]["default"] == "false"
    assert inputs["acknowledge_actions_billing"]["default"] == "false"
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert workflow["jobs"]["ansible"]["needs"] == "qutebrowser"
    assert "continue" in workflow["jobs"]["ansible"]["if"]
    assert "reward" not in workflow["jobs"]["ansible"]["if"]
    assert "model_ready" in workflow["jobs"]["qutebrowser"]["if"]
    for job in workflow["jobs"].values():
        assert "private" in job["steps"][0]["run"]
        assert "GITHUB_RUN_ATTEMPT" in job["steps"][0]["run"]
        uses = [step["uses"] for step in job["steps"] if "uses" in step]
        assert all(len(action.split("@")[1]) == 40 for action in uses)
        raw = [step for step in job["steps"] if "upload-artifact@" in step.get("uses", "")]
        assert len(raw) == 1 and "archive_guard.outputs.private" in raw[0]["if"]
        checkouts = [step for step in job["steps"] if "checkout@" in step.get("uses", "")]
        assert [step["with"]["path"] for step in checkouts] == ["execution", "bench"]
        assert all(step["with"]["persist-credentials"] == "false" for step in checkouts)
    assert "d0cc045d04ccac9d8b7881df0226f9e82c39688e" in text
    assert "prior-paid-records.receipt.json" in text
    assert text.count('--wheel "$GITHUB_WORKSPACE/execution/artifacts/product-baseline.whl"') == 7
    assert text.count("python-version: '3.13.12'") == 3


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"])
@pytest.mark.parametrize(
    "script,argument", [("calibrate_cloud.py", "--wheel"), ("diagnose_wheel.py", "--original")]
)
def test_direct_script_help_supports_sibling_wheel_helper(
    encoding: str, script: str, argument: str
) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        env={**os.environ, "PYTHONIOENCODING": encoding},
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert argument in result.stdout


def test_artifact_entry_error_has_safe_stage_and_reason(
    experiment: Any, monkeypatch: Any, capsys: Any
) -> None:
    e = experiment
    metadata = e.args.output.parent / "repository.json"
    write_json(
        metadata,
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": True, "visibility": "private"},
    )
    monkeypatch.setattr(cloud, "source_identity", lambda *args: e.frozen["source"])

    def rejected(*args: Any) -> Any:
        raise cloud.ArtifactGateError("original_wheel_hash_mismatch")

    monkeypatch.setattr(cloud, "build_baseline", rejected)
    output = e.args.output.parent / "artifact-error"
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate_cloud.py",
            "dry",
            "--root",
            str(e.root),
            "--metadata",
            str(metadata),
            "--source-sha",
            "a" * 40,
            "--workflow",
            str(ROOT / ".github/workflows/cloud-calibration.yml"),
            "--requirements",
            str(e.args.requirements),
            "--artifacts",
            str(e.args.requirements.parent),
            "--output",
            str(output),
        ],
    )
    assert cloud.main() == 1
    report = read_json(output / "entry-error.json")
    assert report["stage"] == "artifact_preflight"
    assert report["reason"] == "original_wheel_hash_mismatch"
    assert report["model_calls_unknown"] is False
    assert "offline-not-a-real-key" not in capsys.readouterr().out


def test_dry_without_ledger_produces_reviewable_identity_without_model(
    experiment: Any, monkeypatch: Any, capsys: Any
) -> None:
    e = experiment
    metadata = e.args.output.parent / "repository.json"
    write_json(
        metadata,
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": True, "visibility": "private"},
    )
    monkeypatch.setattr(cloud, "source_identity", lambda *args: e.frozen["source"])
    monkeypatch.setattr(cloud, "build_baseline", lambda *args: e.frozen["artifacts"])
    output = e.args.output.parent / "dry"
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate_cloud.py",
            "dry",
            "--root",
            str(e.root),
            "--metadata",
            str(metadata),
            "--source-sha",
            "a" * 40,
            "--workflow",
            str(ROOT / ".github/workflows/cloud-calibration.yml"),
            "--requirements",
            str(e.args.requirements),
            "--artifacts",
            str(e.args.requirements.parent),
            "--output",
            str(output),
        ],
    )
    assert cloud.main() == 0
    report = read_json(output / "preflight.json")
    assert report["passed"] is True and report["model_calls"] == 0
    assert report["model_dispatch_ready"] is False
    assert report["ledger_blocker"] == "missing_prior_paid_records"
    assert report["source"]["public_source_sha"] == "a" * 40
    assert not e.calls and "offline-not-a-real-key" not in capsys.readouterr().out


async def test_global_fee_stop_precedes_any_model_call(experiment: Any) -> None:
    e = experiment
    rows = cloud.read_records([e.prior])
    for row in rows:
        row["input_tokens"] = 25_000_000
    save_records(e.prior, rows)
    coverage(e.receipt, e.prior)
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["reason"] == "paid_estimate_stop_fraction_reached"
    assert report["model_started"] is False and not e.calls
    assert not e.args.private_home.exists()


async def test_cloud_subbudget_stops_second_dispatch(experiment: Any) -> None:
    e = experiment
    first = await cloud.calibrate(e.args, e.frozen)
    assert first["continue_allowed"] is True
    path = e.args.output / "run/records.jsonl"
    records = cloud.read_records([path])
    records[0]["input_tokens"] = 6_000_000
    save_records(path, records)
    first["records_sha256"] = file_sha256(path)
    write_json(e.args.output / "calibration.json", first)
    args = argparse.Namespace(**vars(e.args))
    args.fixture = "ansible"
    args.output = e.args.output.parent / "model-ansible"
    args.controls = e.args.output.parent / "controls-ansible"
    _controls(e, "ansible", args.controls)
    args.cloud_prior_records = [path]
    args.cloud_prior_report = e.args.output / "calibration.json"
    report = await cloud.calibrate(args, e.frozen)
    assert report["reason"] == "paid_estimate_stop_fraction_reached"
    assert report["model_started"] is False and len(e.calls) == 1


async def test_current_unknown_usage_is_kept_and_blocks_continuation(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment

    async def incomplete(*args: Any) -> dict[str, Any]:
        await e.fake_run(*args)
        path = args[1] / "records.jsonl"
        record = cloud.read_records([path])[0]
        record["usage_complete"] = False
        save_records(path, [record])
        return {}

    monkeypatch.setattr(cloud, "run_phase", incomplete)
    report = await cloud.calibrate(e.args, e.frozen)
    assert report["continue_allowed"] is False
    assert report["cloud_paid_usage"]["usage_complete"] is False
    assert (e.args.output / "run/records.jsonl").is_file()
    assert len(e.calls) == 1


async def test_invalid_network_probe_prevents_any_control_job(
    experiment: Any, monkeypatch: Any
) -> None:
    e = experiment
    write_json(e.args.probe, {"passed": False, "cleanup_confirmed": False})

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("探针未通过，不得执行 Docker 或 control")

    monkeypatch.setattr(cloud, "resources", forbidden)
    monkeypatch.setattr(cloud, "run_official_trial", forbidden)
    with pytest.raises(ValueError, match="探针"):
        await cloud.controls(
            e.root,
            "qutebrowser",
            e.args.cache,
            e.args.probe,
            e.args.output.parent / "invalid-controls",
        )
