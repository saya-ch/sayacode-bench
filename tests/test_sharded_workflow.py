"""原生 DAG 与私有证据交接的离线测试；不调用 Docker、GitHub 或模型。"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench import shards
from sayacode_bench.artifacts import file_sha256, implementation_identity, read_json, write_json
from scripts import generate_sharded_workflow as module

COHORT = {"ImageOS": "ubuntu24-offline", "ImageVersion": "synthetic-20261022", "RUNNER_ARCH": "X64"}
RELEASE = {
    "repository": "saya-ch/sayacode-bench-runs",
    "release_id": 1,
    "release_tag": "synthetic-evidence",
}


def manifest(archive_sha: str = "b" * 64, size: int = 1) -> dict[str, Any]:
    return {
        "schema_version": 1,
        **RELEASE,
        "repository_id": 2,
        "release_draft_required": True,
        "archive_sha256": archive_sha,
        "archive_size": size,
        "part_size_bytes": 1024**3,
        "parts": [
            {
                "number": 1,
                "size": size,
                "sha256": archive_sha,
                "asset_id": 3,
                "service_digest": "sha256:" + archive_sha,
                "name": f"bundle-{archive_sha}.part-00001-of-00001-{archive_sha}.bin",
            }
        ],
    }


@pytest.fixture
def preparation(tmp_path: Path) -> Path:
    path = tmp_path / "runner-preparation.json"
    write_json(
        path,
        {
            "passed": True,
            "runner_image": COHORT,
            "script_sha256": file_sha256(
                module.TEMPLATE.parents[2] / "scripts/prepare_cloud_runner.py"
            ),
        },
    )
    return path


@pytest.fixture
def frozen(tmp_path: Path) -> SimpleNamespace:
    bundle = tmp_path / "offline"
    inputs = bundle / "inputs"
    inputs.mkdir(parents=True)
    wheel, requirements = inputs / "product.whl", inputs / "requirements.txt"
    wheel.write_bytes(b"offline-wheel")
    requirements.write_bytes(b"offline-lock")
    variants = {}
    for label in ("baseline", "candidate-a", "candidate-b"):
        path = inputs / f"{label}.json"
        write_json(path, {"id": label})
        variants[label] = file_sha256(path)
    master = {
        "phase": "dev",
        "frozen": True,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "configurations": list(variants),
        "baseline": "baseline",
        "repeats": 2,
        "connections": ["first", "second"],
        "seed": "offline-order",
        "connection_profiles": {
            label: {
                "protocol": "anthropic_messages",
                "base_url": "https://example.invalid",
                "model_id": "fixed",
            }
            for label in ("first", "second")
        },
        "artifacts": {
            "product_wheel": file_sha256(wheel),
            "requirements": file_sha256(requirements),
            "variants": variants,
        },
        "tasks": [
            {
                "task_id": f"instance_{index}",
                "environment": {"build_timeout_sec": 1800},
                "agent": {"timeout_sec": 3000},
                "verifier": {"timeout_sec": 3000},
            }
            for index in range(8)
        ],
    }
    original = "/tmp/sayacode-studies/offline"
    runner = {
        "platform": "linux",
        "architecture": "amd64",
        "job_timeout_seconds": 21600,
        "public_source_sha": "a" * 40,
        "executor_workflow_sha256": file_sha256(module.TEMPLATE),
        "host_cohort": COHORT,
        "evidence_release": RELEASE,
    }
    write_json(inputs / "master.json", master)
    write_json(inputs / "runner.json", runner)
    write_json(
        inputs / "authorization.json",
        {
            "authorized": True,
            "phase": "dev",
            "master_manifest_sha256": file_sha256(inputs / "master.json"),
        },
    )

    def reference(name: str) -> dict[str, str]:
        return {"path": original + "/inputs/" + name, "sha256": file_sha256(inputs / name)}

    schedule = shards._schedule(master, reference("master.json")["sha256"])
    plan = {
        "schema_version": 1,
        "bundle_root": original,
        "master": reference("master.json"),
        "runner_policy": reference("runner.json"),
        "authorization": reference("authorization.json"),
        "implementation": implementation_identity(),
        "artifacts": master["artifacts"],
        "schedule": schedule,
        "schedule_sha256": module._hash(schedule),
    }
    path = bundle / "plan.json"
    write_json(path, plan)
    return SimpleNamespace(bundle=bundle, plan=plan, path=path, master=master, runner=runner)


def generate(
    frozen: SimpleNamespace, tmp_path: Path, **kwargs: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = tmp_path / "generated.yml"
    seed = tmp_path / "seed-manifest.json"
    write_json(seed, kwargs.pop("manifest", manifest()))
    receipt = module.generate(frozen.path, frozen.bundle, output, seed_manifest=seed, **kwargs)
    return read_json(output), receipt


def test_full_master_becomes_explicit_serial_dag(frozen: SimpleNamespace, tmp_path: Path) -> None:
    workflow, receipt = generate(frozen, tmp_path)
    assert len(workflow["jobs"]) == 50
    for option in workflow["on"]["workflow_dispatch"]["inputs"].values():
        assert option["default"] is False
    for index, row in enumerate(frozen.plan["schedule"], 1):
        job = workflow["jobs"][f"shard_{index:04d}"]
        previous = f"shard_{index - 1:04d}" if index > 1 else "review"
        assert job["needs"] == [previous]
        assert job["with"]["shard_id"] == row["shard_id"]
        assert "matrix" not in job
        assert "secrets: inherit" not in json.dumps(job)
        if index > 1:
            assert f"needs.{previous}.outputs.continuation_allowed" in job["if"]
            assert (
                f"needs.{previous}.outputs.ledger_sha256" in job["with"]["previous_ledger_sha256"]
            )
    contract = json.loads(workflow["jobs"]["shard_0001"]["with"]["contract_json"])
    assert contract["public_source_sha"] == "a" * 40
    assert contract["plan_sha256"] == file_sha256(frozen.path)
    assert module.load_contract(json.dumps(contract), frozen.bundle)[1] == frozen.plan
    assert receipt["shard_count"] == 48
    assert receipt["planned_reserve_seconds"] == 48 * 17700
    assert receipt["execution_authorized_by_generation"] is False
    assert receipt["host_cohort_enforced"] is True
    assert receipt["host_cohort_fields"] == ["ImageOS", "ImageVersion", "RUNNER_ARCH"]
    assert "physical_cpu_identity" in receipt["host_cohort_exclusions"]
    assert "不是永久免费" in receipt["storage_note"]
    assert workflow["permissions"]["contents"] == "write"


def test_release_seed_is_bound_to_frozen_release(frozen: SimpleNamespace, tmp_path: Path) -> None:
    workflow, _ = generate(frozen, tmp_path)
    first = workflow["jobs"]["shard_0001"]["with"]
    assert json.loads(first["evidence_manifest_json"]) == manifest()
    assert "input_artifact" not in first and "seed_file" not in first
    assert (
        "outputs.evidence_manifest_json"
        in workflow["jobs"]["shard_0002"]["with"]["evidence_manifest_json"]
    )
    assert workflow["jobs"]["merge"]["needs"] == ["shard_0048"]
    assert "secrets" not in workflow["jobs"]["merge"]


@pytest.mark.parametrize(
    "change",
    ["schedule", "source", "template", "authorization", "timeout", "key", "implementation"],
)
def test_generation_fails_closed_on_drift(
    frozen: SimpleNamespace, tmp_path: Path, change: str
) -> None:
    plan = copy.deepcopy(frozen.plan)
    if change == "schedule":
        plan["schedule"].reverse()
        plan["schedule_sha256"] = module._hash(plan["schedule"])
    elif change == "implementation":
        plan["implementation"]["worker.py"] = "c" * 64
    else:
        name = (
            "runner.json"
            if change in {"source", "template", "timeout"}
            else "authorization.json"
            if change == "authorization"
            else "master.json"
        )
        path = frozen.bundle / "inputs" / name
        value = read_json(path)
        if change == "source":
            value["public_source_sha"] = "main"
        elif change == "template":
            value["executor_workflow_sha256"] = "c" * 64
        elif change == "timeout":
            value["job_timeout_seconds"] = 3600
        elif change == "authorization":
            value["authorized"] = False
        else:
            value["connection_profiles"]["first"]["api_key"] = "offline-secret"
        write_json(path, value)
        field = {
            "runner.json": "runner_policy",
            "authorization.json": "authorization",
            "master.json": "master",
        }[name]
        plan[field]["sha256"] = file_sha256(path)
    write_json(frozen.path, plan)
    with pytest.raises(ValueError):
        generate(frozen, tmp_path)


@pytest.mark.parametrize(
    "cohort",
    [
        None,
        {},
        {**COHORT, "ImageOS": ""},
        {**COHORT, "ImageVersion": " "},
        {**COHORT, "RUNNER_ARCH": "ARM64"},
        {**COHORT, "cpu": "same"},
    ],
)
def test_generation_requires_exact_frozen_image_cohort(
    frozen: SimpleNamespace, tmp_path: Path, cohort: Any
) -> None:
    path = frozen.bundle / "inputs/runner.json"
    runner = read_json(path)
    runner["host_cohort"] = cohort
    write_json(path, runner)
    frozen.plan["runner_policy"]["sha256"] = file_sha256(path)
    write_json(frozen.path, frozen.plan)
    with pytest.raises(ValueError):
        generate(frozen, tmp_path)


@pytest.mark.parametrize(
    "key,value",
    [
        ("repository", "public/repo"),
        ("release_id", 2),
        ("release_tag", "other"),
        ("archive_sha256", "bad"),
    ],
)
def test_seed_manifest_cannot_escape_frozen_release(
    frozen: SimpleNamespace, tmp_path: Path, key: str, value: Any
) -> None:
    seed = manifest()
    seed[key] = value
    with pytest.raises(ValueError):
        generate(frozen, tmp_path, manifest=seed)


def test_generation_never_overwrites_reviewed_dag(frozen: SimpleNamespace, tmp_path: Path) -> None:
    generate(frozen, tmp_path)
    with pytest.raises(FileExistsError):
        generate(frozen, tmp_path)


def test_template_has_real_cli_probe_pins_and_secret_boundary() -> None:
    text = module.TEMPLATE.read_text(encoding="utf-8")
    # BaseLoader 保留 YAML 的 on 键及所有标量，避免 YAML1.1 布尔误读。
    value = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(value["on"]) == {"workflow_call"}
    job = value["jobs"]["run"]
    assert job["timeout-minutes"] == "360"
    actions = [step["uses"] for step in job["steps"] if "uses" in step]
    assert all(module.COMMIT.fullmatch(action.rsplit("@", 1)[1]) for action in actions)
    assert "prepare_cloud_runner.py" in text
    assert "test_real_docker_network_isolation" in text
    assert "-m scripts.generate_sharded_workflow execute" in text
    assert "-m scripts.generate_sharded_workflow merge" in text
    assert "retention-days: 3" in text
    assert "delete-artifact" not in text
    secret_steps = [
        step for step in job["steps"] if "secrets.connection_keys_json" in json.dumps(step)
    ]
    assert len(secret_steps) == 1
    assert "execute" in secret_steps[0]["run"]
    assert "GH_TOKEN" not in secret_steps[0].get("env", {})
    assert value["permissions"]["contents"] == "write"
    assert not any(action.startswith("actions/download-artifact@") for action in actions)
    uploads = [
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert all("/archive/" not in step["with"]["path"] for step in uploads)
    stage = next(step for step in job["steps"] if "actions-evidence" in step.get("run", ""))
    assert "steps.archive.outcome" not in stage.get("if", "")
    assert stage["env"]["RELEASE_TRANSFER_OUTCOME"] == "${{ steps.archive.outcome }}"
    assert sum("gh api" in step.get("run", "") for step in job["steps"]) == 2
    assert all(
        step.get("with", {}).get("persist-credentials", "false") == "false"
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )


def test_full_raw_bundle_round_trip_and_source_paths_unchanged(
    tmp_path: Path, monkeypatch: Any
) -> None:
    bundle = tmp_path / "bundle"
    raw = bundle / "shards/one/run/native"
    raw.mkdir(parents=True)
    (raw / "output.bin").write_bytes(bytes(range(256)) * 64)
    write_json(raw / "config.json", {"path": "/tmp/sayacode-studies/fixed/raw"})
    write_json(
        bundle / "orchestration/one/dispatch.json",
        {"continuation_allowed": True, "receipt_sha256": "a" * 64, "ledger_sha256": "b" * 64},
    )
    contract = json.dumps(
        {"bundle_root": str(bundle), "plan_sha256": "c" * 64, "evidence_release": RELEASE}
    )
    monkeypatch.setattr(
        module,
        "upload_archive",
        lambda archive, **_: manifest(file_sha256(archive), archive.stat().st_size),
    )
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10**14))
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    output = tmp_path / "archive"
    result = module.archive_bundle(contract, output, shard_id="one")
    restored = tmp_path / "restored"
    module.restore_archive(output / "bundle.tar.gz", restored, result["archive_sha256"])
    assert (restored / "shards/one/run/native/output.bin").read_bytes() == (
        raw / "output.bin"
    ).read_bytes()
    assert (
        read_json(restored / "shards/one/run/native/config.json")["path"]
        == "/tmp/sayacode-studies/fixed/raw"
    )
    assert result["cloud_artifact_deletion_performed"] is False
    assert result["archive_bytes"] > 0
    assert read_json(output / "archive-receipt.json")["transfer_status"] == "completed"
    exported = dict(
        line.split("=", 1) for line in github_output.read_text(encoding="utf-8").splitlines()
    )
    assert (
        json.loads(exported["evidence_manifest_json"])["archive_sha256"] == result["archive_sha256"]
    )
    with pytest.raises(FileExistsError):
        module.restore_archive(output / "bundle.tar.gz", restored, result["archive_sha256"])


@pytest.mark.parametrize("kind", ["path", "symlink", "hardlink", "duplicate"])
def test_restore_rejects_unsafe_or_ambiguous_archive(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "bad.tar"
    with tarfile.open(path, "w") as stream:
        member = tarfile.TarInfo("../outside" if kind == "path" else "file")
        if kind in {"symlink", "hardlink"}:
            member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "/tmp/private"
        member.size = 0
        stream.addfile(member, io.BytesIO())
        if kind == "duplicate":
            stream.addfile(member, io.BytesIO())
    with pytest.raises(ValueError):
        module.restore_archive(path, tmp_path / "new", file_sha256(path))
    assert not (tmp_path / "new").exists()


def test_previous_receipt_and_ledger_both_bind_before_dispatch(tmp_path: Path) -> None:
    plan = {"bundle_root": str(tmp_path), "schedule": [{"shard_id": "one"}, {"shard_id": "two"}]}
    ledger = tmp_path / "shards/one/ledger.json"
    write_json(ledger, {"phase_records": []})
    receipt = ledger.with_name("shard-receipt.json")
    write_json(
        receipt,
        {
            "ledger_after": {"path": str(ledger), "sha256": file_sha256(ledger)},
            "continuation_allowed": True,
        },
    )
    assert (
        module.verify_previous(plan, {"sequence": 2}, file_sha256(receipt), file_sha256(ledger))
        == receipt
    )
    write_json(ledger, {"phase_records": [{"tampered": True}]})
    with pytest.raises(ValueError):
        module.verify_previous(plan, {"sequence": 2}, file_sha256(receipt), file_sha256(ledger))


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("merge_rc", [1, 2])
@pytest.mark.parametrize("native_rc", [0, 2])
def test_execute_uses_native_cli_then_cleans_only_own_credentials(
    tmp_path: Path, monkeypatch: Any, fail: bool, merge_rc: int, native_rc: int, preparation: Path
) -> None:
    bundle = tmp_path / "study"
    bundle.mkdir()
    private = tmp_path / "private"
    unrelated = tmp_path / "existing-private.json"
    unrelated.write_text("leave me", encoding="utf-8")
    entry = {"shard_id": "one", "sequence": 1, "reserve_seconds": 100}
    plan = {"bundle_root": str(bundle), "schedule": [entry]}
    master = {
        "connections": ["remote"],
        "connection_profiles": {"remote": {"protocol": "anthropic_messages"}},
    }
    contract = {
        "host_cohort": COHORT,
        "private_home": str(private),
        "plan_relative_path": "plan.json",
        "bindings": {
            "wheel": "inputs/product.whl",
            "requirements": "inputs/requirements.txt",
            "variants": {"baseline": "inputs/baseline.json"},
        },
    }
    monkeypatch.setattr(module, "load_contract", lambda _: (contract, plan, master))
    monkeypatch.setattr(module, "_private_directory", lambda *_: private)
    monkeypatch.setattr(module, "verify_previous", lambda *_: None)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=10**14))
    monkeypatch.setenv("SAYACODE_STUDY_CONNECTION_KEYS_JSON", '{"remote":"offline-secret"}')
    probe = tmp_path / "probe.json"
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {"network.py": implementation_identity()["network.py"]},
        },
    )

    async def image(*_: Any) -> dict[str, bool]:
        return {"offline": True}

    monkeypatch.setattr(module, "prepare_image", image)
    calls = []

    def native(arguments: list[str], log: Path, **_: Any) -> int:
        calls.append(arguments)
        assert arguments[0] == "run-shard"
        assert "--deadline-epoch" in arguments
        assert "offline-secret" not in str(arguments)
        assert read_json(private / "remote.json")["api_key"] == "offline-secret"
        gateway = private / "runs/run/remote-gateway.json"
        write_json(gateway, {"api_key": "offline-secret"})
        if fail:
            raise OSError("private failure正文")
        write_json(
            bundle / "shards/one/shard-receipt.json",
            {"ledger_after": {"sha256": "a" * 64}, "complete": True, "continuation_allowed": True},
        )
        return native_rc

    monkeypatch.setattr(module, "_cli", native)
    monkeypatch.setattr(module, "merge", lambda *_args, **_kwargs: merge_rc)
    result = module.execute(
        "offline", "one", probe=probe, runner_preparation=preparation, deadline=time.time() + 200
    )
    assert len(calls) == 1
    assert not private.exists()
    assert unrelated.read_text(encoding="utf-8") == "leave me"
    assert result["credential_cleanup_confirmed"] is True
    assert result["host_cohort_confirmed"] is True
    assert result["continuation_allowed"] is (not fail and merge_rc == 1 and native_rc == 0)
    assert "private failure正文" not in json.dumps(result)
    assert "offline-secret" not in (bundle / "orchestration/one/dispatch.json").read_text(
        encoding="utf-8"
    )


def test_cli_child_environment_does_not_receive_key_json(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SAYACODE_STUDY_CONNECTION_KEYS_JSON", "must-not-inherit")
    monkeypatch.setenv("GH_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert command[1:3] == ["-m", "sayacode_bench.cli"]
        assert "SAYACODE_STUDY_CONNECTION_KEYS_JSON" not in kwargs["env"]
        assert "GH_TOKEN" not in kwargs["env"] and "GITHUB_TOKEN" not in kwargs["env"]
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", run)
    assert module._cli(["merge-shards"], tmp_path / "entry.log") == 1
    assert os.environ["SAYACODE_STUDY_CONNECTION_KEYS_JSON"] == "must-not-inherit"


def test_insufficient_native_time_never_reads_keys_or_starts_source(
    tmp_path: Path, monkeypatch: Any, preparation: Path
) -> None:
    bundle = tmp_path / "study"
    bundle.mkdir()
    private = tmp_path / "private"
    plan = {
        "bundle_root": str(bundle),
        "schedule": [{"shard_id": "one", "sequence": 1, "reserve_seconds": 100}],
    }
    monkeypatch.setattr(module, "load_contract", lambda _: ({"host_cohort": COHORT}, plan, {}))
    monkeypatch.setattr(module, "_private_directory", lambda *_: private)
    monkeypatch.setattr(module, "verify_previous", lambda *_: None)
    monkeypatch.setenv("SAYACODE_STUDY_CONNECTION_KEYS_JSON", "invalid JSON must not be read")
    probe = tmp_path / "probe.json"
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {"network.py": implementation_identity()["network.py"]},
        },
    )

    def forbidden(*_: Any, **__: Any) -> None:
        pytest.fail("时间不足时不得准备镜像或启动 CLI")

    monkeypatch.setattr(module, "prepare_image", forbidden)
    monkeypatch.setattr(module, "_cli", forbidden)
    result = module.execute(
        "offline", "one", probe=probe, runner_preparation=preparation, deadline=time.time() + 50
    )
    assert result["model_dispatch_attempted"] is False
    assert result["continuation_allowed"] is False
    assert result["error_type"] == "ValueError"
    assert not private.exists()


@pytest.mark.parametrize(
    "change", ["ImageOS", "ImageVersion", "RUNNER_ARCH", "script_sha256", "passed"]
)
def test_host_drift_preserves_real_preparation_and_never_reads_secret(
    tmp_path: Path, monkeypatch: Any, preparation: Path, change: str
) -> None:
    bundle = tmp_path / "study"
    bundle.mkdir()
    private = tmp_path / "private"
    actual = read_json(preparation)
    if change in COHORT:
        actual["runner_image"][change] = "drifted"
    elif change == "passed":
        actual[change] = False
    else:
        actual[change] = "f" * 64
    write_json(preparation, actual)
    plan = {
        "bundle_root": str(bundle),
        "schedule": [{"shard_id": "one", "sequence": 1, "reserve_seconds": 100}],
    }
    monkeypatch.setattr(module, "load_contract", lambda _: ({"host_cohort": COHORT}, plan, {}))
    monkeypatch.setattr(module, "_private_directory", lambda *_: private)
    monkeypatch.setenv("SAYACODE_STUDY_CONNECTION_KEYS_JSON", "not JSON; must not be parsed")

    def forbidden(*_: Any, **__: Any) -> None:
        pytest.fail("cohort 漂移必须在镜像、模型 CLI 及 Secret 读取之前停止")

    monkeypatch.setattr(module, "verify_previous", forbidden)
    monkeypatch.setattr(module, "prepare_image", forbidden)
    monkeypatch.setattr(module, "_cli", forbidden)
    result = module.execute(
        "offline",
        "one",
        probe=tmp_path / "absent-probe.json",
        runner_preparation=preparation,
        deadline=time.time() + 200,
    )
    assert result["host_cohort_confirmed"] is False
    assert result["model_dispatch_attempted"] is False
    assert result["error_type"] == "ValueError"
    assert result["expected_host_cohort"] == COHORT
    assert result["observed_host_cohort"] == actual["runner_image"]
    assert read_json(bundle / "orchestration/one/runner-preparation.json") == actual
    assert result["runner_preparation_sha256"] == file_sha256(preparation)
    assert not private.exists()


def test_real_module_help_and_lazy_image_import_without_pytest_pythonpath() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    root = module.TEMPLATE.parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "scripts.generate_sharded_workflow", "--help"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0
    assert "generate" in result.stdout and "restore" in result.stdout
    # 在与模块入口相同的 cwd 中触发延迟 import；固定镜像函数替身不调用 Docker。
    code = """
import asyncio, json
from scripts import diagnose_fixtures, generate_sharded_workflow
async def pin(fixture):
    assert fixture['immutable_image'] == 'registry.invalid/task@sha256:' + 'b'*64
    return {'expected_image_id':'sha256:'+'a'*64,'os':'linux','architecture':'amd64'}
diagnose_fixtures.pin_image = pin
master = {'tasks':[{'task_id':'offline','environment':{'docker_image':'registry.invalid/task:original'}}],
          'qualified_runtime_identities':{'offline':{'image_id':'sha256:'+'a'*64,
                                                   'repo_digests':['registry.invalid/task@sha256:'+'b'*64]}}}
value = asyncio.run(generate_sharded_workflow.prepare_image(master, {'task_id':'offline'}))
print(json.dumps({'lazy_import_and_mock_pin':value['os']=='linux'}))
"""
    imported = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert imported.returncode == 0
    assert json.loads(imported.stdout)["lazy_import_and_mock_pin"] is True


def test_release_manifest_is_single_line_bounded_and_not_arbitrary_output() -> None:
    value = manifest()
    value["billing_boundary"] = "中文\nnot-an-output=secret"
    serialized = module._manifest_json(value, RELEASE)
    assert "\n" not in serialized and "\r" not in serialized
    assert json.loads(serialized) == value
    value["large"] = "x" * module.MAX_MANIFEST_CHARACTERS
    with pytest.raises(ValueError, match="输出范围"):
        module._manifest_json(value, RELEASE)


def test_release_upload_failure_keeps_complete_tar_and_failed_receipt_for_current_raw(
    tmp_path: Path, monkeypatch: Any
) -> None:
    bundle = tmp_path / "bundle"
    raw = bundle / "shards/one/run/native/output.bin"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"private complete raw including reasoning")

    def fail(*_: Any, **__: Any) -> None:
        raise ValueError("synthetic transfer failure")

    monkeypatch.setattr(module, "upload_archive", fail)
    output = tmp_path / "archive"
    with pytest.raises(ValueError):
        module.archive_bundle(
            json.dumps(
                {"bundle_root": str(bundle), "plan_sha256": "c" * 64, "evidence_release": RELEASE}
            ),
            output,
            shard_id="one",
        )
    assert raw.read_bytes() == b"private complete raw including reasoning"
    assert (output / "bundle.tar.gz").is_file()
    assert read_json(output / "archive-receipt.json")["transfer_status"] == "failed"
    assert not (output / "evidence-manifest.json").exists()


def test_release_download_handoff_keeps_native_restore_sha_and_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    contract: dict[str, Any] = {
        "bundle_root": "/tmp/sayacode-studies/offline",
        "public_source_sha": "a" * 40,
        "evidence_release": RELEASE,
    }
    evidence = manifest()
    monkeypatch.setenv("SAYACODE_STUDY_CONTRACT", json.dumps(contract))
    monkeypatch.setenv("SAYACODE_EVIDENCE_MANIFEST", json.dumps(evidence))
    monkeypatch.setattr(
        sys, "argv", ["generator", "restore", "--download-dir", str(tmp_path / "download")]
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=("a" * 40).encode("utf-8")),
    )
    downloaded = tmp_path / "bundle.tar.gz"
    calls = []

    def download(value: dict[str, Any], **kwargs: Any) -> Path:
        assert value == evidence
        assert {key: kwargs[key] for key in RELEASE} == RELEASE
        return downloaded

    monkeypatch.setattr(module, "download_archive", download)
    monkeypatch.setattr(module, "restore_archive", lambda *args: calls.append(args))
    monkeypatch.setattr(module, "load_contract", lambda _: None)
    assert module.main() == 0
    assert calls == [(downloaded, Path(contract["bundle_root"]), evidence["archive_sha256"])]


@pytest.mark.parametrize(
    ("native_rc", "complete", "continuation", "error", "expected"),
    [
        (0, True, True, None, 0),
        (0, True, False, None, 0),
        (1, True, False, None, 1),
        (0, False, False, None, 1),
        (0, True, True, "ValueError", 1),
    ],
)
def test_incomplete_native_shard_cannot_make_actions_green(
    monkeypatch: Any,
    native_rc: int,
    complete: bool,
    continuation: bool,
    error: str | None,
    expected: int,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_sharded_workflow.py",
            "execute",
            "--contract",
            "offline",
            "--shard-id",
            "one",
            "--probe",
            "offline.json",
            "--runner-preparation",
            "offline-preparation.json",
            "--deadline-epoch",
            "21600",
        ],
    )
    monkeypatch.setattr(
        module,
        "execute",
        lambda *_args, **_kwargs: {
            "error_type": error,
            "native_cli_returncode": native_rc,
            "receipt_complete": complete,
            "continuation_allowed": continuation,
        },
    )
    assert module.main() == expected


@pytest.mark.parametrize(
    "state", ["confirmed", "failed", "missing_manifest", "failed_step", "mismatch"]
)
def test_actions_retains_raw_only_when_release_transfer_is_not_confirmed(
    tmp_path: Path, monkeypatch: Any, state: str
) -> None:
    value = yaml.load(module.TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    stage = next(
        step for step in value["jobs"]["run"]["steps"] if "actions-evidence" in step.get("run", "")
    )
    code = stage["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    temporary, bundle = tmp_path / "temporary", tmp_path / "bundle"
    current = bundle / "shards/one"
    raw = current / "run/jobs/native/private-trajectory.bin"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(bytes(range(256)) * 16)
    write_json(current / "shard-receipt.json", {"complete": True})
    write_json(current / "run/summary.json", {"descriptive": "summary"})
    orchestration = bundle / "orchestration/one"
    write_json(orchestration / "dispatch.json", {"continuation_allowed": True})
    (orchestration / "entry.log").write_text("raw child CLI output", encoding="utf-8")
    old = bundle / "shards/old/run/native.bin"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"previous prefix must not be copied into Actions")
    receipt = {"transfer_status": "completed", "archive_sha256": "b" * 64, "archive_bytes": 1000}
    if state == "failed":
        receipt["transfer_status"] = "failed"
    write_json(temporary / "archive/archive-receipt.json", receipt)
    if state != "missing_manifest":
        write_json(
            temporary / "archive/evidence-manifest.json",
            {
                "archive_sha256": "c" * 64 if state == "mismatch" else "b" * 64,
                "archive_size": 1000,
            },
        )
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    monkeypatch.setenv("BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("SHARD_ID", "one")
    monkeypatch.setenv(
        "RELEASE_TRANSFER_OUTCOME", "failure" if state == "failed_step" else "success"
    )
    exec(compile(code, "<offline-actions-stage>", "exec"), {})
    copied = temporary / "actions-evidence"
    assert (copied / "shards/one/run/summary.json").is_file()
    assert (copied / "shards/one/shard-receipt.json").is_file()
    assert not (copied / "shards/old").exists()
    if state == "confirmed":
        assert not (copied / "shards/one/run/jobs").exists()
        assert not (copied / "orchestration/one/entry.log").exists()
    else:
        assert (
            copied / "shards/one/run/jobs/native/private-trajectory.bin"
        ).read_bytes() == raw.read_bytes()
        assert (copied / "orchestration/one/entry.log").is_file()
    policy = read_json(copied / "evidence-policy.json")
    assert policy["release_transfer_confirmed"] is (state == "confirmed")
    assert policy["raw_current_shard_retained"] is (state != "confirmed")
