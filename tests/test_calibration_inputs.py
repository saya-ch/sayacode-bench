"""固定云端输入的离线预检：异常位置、元数据与镜像观察；不调用真实 Docker。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.sources import SOURCES, SourceSnapshot, tree_digest
from scripts import calibrate_cloud as cloud
from scripts import diagnose_fixtures as diagnostic

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: Any) -> Any:
    root = tmp_path / "bench"
    snapshot = tmp_path / "cache/snapshot"
    spec = SOURCES["swe-bench-pro-v2"]
    tasks = []
    for task_id, _ in cloud.FIXTURES.values():
        path = snapshot / spec.tasks_path / task_id
        path.mkdir(parents=True)
        (path / "instruction.md").write_text("A fixed calibration input.\n", encoding="utf-8")
        (path / "task.toml").write_text('version="1.0"\n', encoding="utf-8")
        tasks.append(
            {
                "task_id": task_id,
                "instruction_sha256": file_sha256(path / "instruction.md"),
                "config_sha256": file_sha256(path / "task.toml"),
                "task_tree_sha256": tree_digest(path),
                "environment": {
                    "docker_image": f"{cloud.IMAGE_REPOSITORY}:{task_id}",
                    "cpus": 1,
                    "memory_mb": 4096,
                },
            }
        )
    write_json(
        root / "studies/calibration.json",
        {
            "phase": "calibration",
            "revision": cloud.REVISION,
            "tasks": tasks,
        },
    )
    monkeypatch.setattr(cloud, "fetch_source", lambda *args: SourceSnapshot(spec, snapshot, "a", 0))
    monkeypatch.setattr(
        cloud.shutil, "disk_usage", lambda *args: SimpleNamespace(free=100 * 1024**3)
    )
    calls = []

    async def execute(*args: str, **kwargs: Any) -> str:
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            fixture = next(
                name for name, (task_id, _) in cloud.FIXTURES.items() if args[2].endswith(task_id)
            )
            return json.dumps(
                [
                    {
                        "Id": "sha256:" + "a" * 64,
                        "RepoDigests": [f"{cloud.IMAGE_REPOSITORY}@{cloud.FIXTURES[fixture][1]}"],
                        "Architecture": "amd64",
                        "Os": "linux",
                        "Config": {"Env": ["PRIVATE_TOKEN=never-export-this"]},
                    }
                ]
            )
        return ""

    monkeypatch.setattr(cloud, "docker", execute)
    return SimpleNamespace(
        root=root,
        cache=tmp_path / "cache",
        output=tmp_path / "evidence",
        calls=calls,
        execute=execute,
        tasks=tasks,
    )


@pytest.mark.parametrize("field", ["instruction_sha256", "config_sha256", "task_tree_sha256"])
def test_task_identity_rejection_has_specific_safe_reason(inputs: Any, field: str) -> None:
    path = inputs.root / "studies/calibration.json"
    template = read_json(path)
    template["tasks"][0][field] = "f" * 64
    write_json(path, template)
    with pytest.raises(cloud.ArtifactGateError) as error:
        cloud.task_row(inputs.root, "qutebrowser", inputs.cache)
    assert error.value.reason == f"calibration_{field}_mismatch"
    assert not inputs.calls


def test_task_set_rejection_is_distinct_from_content_mismatch(inputs: Any) -> None:
    path = inputs.root / "studies/calibration.json"
    template = read_json(path)
    template["tasks"].pop()
    write_json(path, template)
    with pytest.raises(cloud.ArtifactGateError) as error:
        cloud.task_row(inputs.root, "qutebrowser", inputs.cache)
    assert error.value.reason == "calibration_task_set_mismatch"


def test_traceback_exports_only_repo_relative_locations() -> None:
    secret = "never-export-exception-or-local-value"
    try:
        raise RuntimeError(secret)
    except RuntimeError as exc:
        frames = cloud.repo_traceback_frames(exc, ROOT)
    assert frames
    assert all(set(frame) == {"file", "line", "function"} for frame in frames)
    assert all(not Path(frame["file"]).is_absolute() for frame in frames)
    encoded = json.dumps(frames)
    assert secret not in encoded and str(ROOT) not in encoded
    assert frames[-1]["file"] == "tests/test_calibration_inputs.py"


@pytest.mark.parametrize(
    "probe,reason",
    [
        ({"passed": False}, "network_probe_not_passed"),
        ({"passed": True, "cleanup_confirmed": False}, "network_probe_cleanup_unconfirmed"),
        (
            {"passed": True, "cleanup_confirmed": True, "source_sha256": {"network.py": "wrong"}},
            "network_probe_implementation_mismatch",
        ),
    ],
)
async def test_probe_rejections_have_specific_reasons_before_docker(
    inputs: Any, probe: dict[str, Any], reason: str
) -> None:
    path = inputs.output.parent / "probe.json"
    write_json(path, probe)
    with pytest.raises(cloud.ArtifactGateError) as error:
        await cloud.controls(inputs.root, "qutebrowser", inputs.cache, path, inputs.output)
    assert error.value.reason == reason
    assert not inputs.calls


async def test_prepare_pins_only_fixed_two_images_and_exports_safe_observations(
    inputs: Any, monkeypatch: Any
) -> None:
    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("输入预检不得运行参考解、Agent 或模型")

    monkeypatch.setattr(cloud, "run_official_trial", forbidden)
    monkeypatch.setattr(cloud, "run_phase", forbidden)
    prepared = await cloud.prepare_inputs(inputs.root, inputs.cache, inputs.output)
    report = read_json(inputs.output / "image-preparation.json")
    assert set(prepared) == set(cloud.FIXTURES)
    assert report["passed"] is True and report["complete"] is True
    assert report["model_calls"] == report["control_jobs"] == 0
    assert len(inputs.calls) == 6
    for row in report["fixtures"]:
        assert row["task_metadata_confirmed"] is True and row["passed"] is True
        assert set(row["inspect"]) == {"Id", "RepoDigests", "Architecture", "Os"}
    assert "never-export-this" not in json.dumps(report)
    assert "Config" not in json.dumps(report)


async def test_bad_second_digest_preserves_first_and_actual_inspect(
    inputs: Any, monkeypatch: Any
) -> None:
    async def bad_second(*args: str, **kwargs: Any) -> str:
        result = await inputs.execute(*args, **kwargs)
        if args[:2] == ("image", "inspect") and args[2].endswith(cloud.FIXTURES["ansible"][0]):
            value = json.loads(result)
            value[0]["RepoDigests"] = ["ghcr.io/example/wrong@sha256:" + "b" * 64]
            return json.dumps(value)
        return result

    monkeypatch.setattr(cloud, "docker", bad_second)
    with pytest.raises(cloud.ArtifactGateError) as error:
        await cloud.prepare_inputs(inputs.root, inputs.cache, inputs.output)
    assert error.value.reason == "image_pin_validation_failed"
    report = read_json(inputs.output / "image-preparation.json")
    assert report["complete"] is False and report["passed"] is False
    assert report["fixtures"][0]["passed"] is True
    failed = report["fixtures"][1]
    assert failed["inspect"]["RepoDigests"] == ["ghcr.io/example/wrong@sha256:" + "b" * 64]
    assert failed["reason"] == "image_pin_validation_failed"
    assert "never-export-this" not in json.dumps(report)


async def test_invalid_inspect_json_keeps_only_safe_type_and_hash(
    inputs: Any, monkeypatch: Any
) -> None:
    async def invalid(*args: str, **kwargs: Any) -> str:
        if args[:2] == ("image", "inspect"):
            return "not-json-and-never-export-this"
        return ""

    monkeypatch.setattr(cloud, "docker", invalid)
    with pytest.raises(cloud.ArtifactGateError) as error:
        await cloud.prepare_inputs(inputs.root, inputs.cache, inputs.output)
    assert error.value.reason == "image_inspection_invalid_json"
    report = read_json(inputs.output / "image-preparation.json")
    item = report["fixtures"][0]
    assert item["inspection_shape_confirmed"] is False
    assert len(item["inspection_stdout_sha256"]) == 64
    assert "not-json-and-never-export-this" not in json.dumps(report)


@pytest.mark.parametrize("injected", [False, True])
async def test_shared_pin_image_default_and_injected_paths_match(
    inputs: Any, monkeypatch: Any, injected: bool
) -> None:
    descriptor = {
        "immutable_image": f"{cloud.IMAGE_REPOSITORY}@{cloud.FIXTURES['qutebrowser'][1]}",
        "original_image_reference": f"{cloud.IMAGE_REPOSITORY}:{cloud.FIXTURES['qutebrowser'][0]}",
    }

    async def forbidden(*args: Any, **kwargs: Any) -> str:
        pytest.fail("显式注入后不得使用默认 Docker")

    monkeypatch.setattr(diagnostic, "docker", forbidden if injected else inputs.execute)
    result = await diagnostic.pin_image(
        descriptor, **({"docker_call": inputs.execute} if injected else {})
    )
    assert result["expected_repo_digest"] == descriptor["immutable_image"]
    assert len(inputs.calls) == 3


def test_dry_with_cache_prepares_inputs_before_model_gate(inputs: Any, monkeypatch: Any) -> None:
    metadata = inputs.output.parent / "repository.json"
    write_json(
        metadata,
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": True, "visibility": "private"},
    )
    monkeypatch.setattr(cloud, "source_identity", lambda *args: {"public_source_sha": "a" * 40})
    monkeypatch.setattr(
        cloud, "build_baseline", lambda *args: {"wheel_selection": "explicit_original"}
    )
    original_get = cloud.os.environ.get

    def guarded_get(key: str, *args: Any) -> Any:
        assert key != "SAYACODE_BENCH_MODEL_API_KEY", "dry不得读取模型密钥"
        return original_get(key, *args)

    monkeypatch.setattr(cloud.os.environ, "get", guarded_get)
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate_cloud.py",
            "dry",
            "--root",
            str(inputs.root),
            "--metadata",
            str(metadata),
            "--source-sha",
            "a" * 40,
            "--workflow",
            str(ROOT / ".github/workflows/cloud-calibration.yml"),
            "--requirements",
            str(inputs.output.parent / "requirements.txt"),
            "--artifacts",
            str(inputs.output.parent / "artifacts"),
            "--cache",
            str(inputs.cache),
            "--output",
            str(inputs.output),
        ],
    )
    assert cloud.main() == 0
    report = read_json(inputs.output / "preflight.json")
    assert report["passed"] is True
    assert report["input_preparation"]["passed"] is True
    assert report["model_dispatch_ready"] is False
    assert report["ledger_blocker"] == "missing_prior_paid_records"
    assert len(inputs.calls) == 6


def test_main_exports_safe_frames_for_unknown_failure(
    inputs: Any, monkeypatch: Any, capsys: Any
) -> None:
    metadata = inputs.output.parent / "repository.json"
    write_json(
        metadata,
        {"full_name": cloud.EXECUTION_REPOSITORY, "private": True, "visibility": "private"},
    )

    def rejected(*args: Any) -> Any:
        hidden_local = "not-a-real-key-but-do-not-export"
        raise ValueError(hidden_local)

    monkeypatch.setattr(cloud, "source_identity", rejected)
    monkeypatch.setattr(
        "sys.argv",
        [
            "calibrate_cloud.py",
            "dry",
            "--root",
            str(ROOT),
            "--metadata",
            str(metadata),
            "--source-sha",
            "a" * 40,
            "--workflow",
            str(ROOT / ".github/workflows/cloud-calibration.yml"),
            "--requirements",
            str(inputs.output.parent / "requirements.txt"),
            "--artifacts",
            str(inputs.output.parent / "artifacts"),
            "--output",
            str(inputs.output),
        ],
    )
    assert cloud.main() == 1
    report = read_json(inputs.output / "entry-error.json")
    assert report["stage"] == "source_identity" and report["reason"] == "source_identity_failed"
    assert report["traceback_frames"]
    assert all(set(frame) == {"file", "line", "function"} for frame in report["traceback_frames"])
    assert "not-a-real-key-but-do-not-export" not in json.dumps(report)
    assert "not-a-real-key-but-do-not-export" not in capsys.readouterr().out


def test_workflow_all_dry_steps_include_same_explicit_cache() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/cloud-calibration.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    count = 0
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "scripts/calibrate_cloud.py dry" in step.get("run", ""):
                assert '--cache "$RUNNER_TEMP/cloud-source"' in step["run"]
                count += 1
    assert count == 3
