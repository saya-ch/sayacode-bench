"""稳定性复核保持固定次数，不能失败后只挑成功记录。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sayacode_bench.artifacts import read_json, write_json


def load_script():
    path = Path(__file__).parents[1] / "scripts" / "verify_calibration_stability.py"
    spec = importlib.util.spec_from_file_location("stability_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path):
    source_job = tmp_path / "experiment" / "jobs" / "calibration-source"
    write_json(
        source_job.parent.parent / "manifest.json",
        {
            "phase": "calibration",
            "benchmark": "swe-bench-pro-v2",
            "tasks": [{"task_id": "known-calibration"}],
        },
    )
    write_json(
        source_job / "normalized.json",
        {
            "task_id": "known-calibration",
            "canonical_model": "DeepSeek-V4.1-Flash",
            "endpoint": "local",
            "task_checksum": "same-task",
        },
    )
    write_json(source_job / "config.json", {"environment": {"type": "docker"}})
    patch = source_job / "instance_known__one" / "agent" / "model.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"fixed patch\n")
    snapshot = SimpleNamespace(
        tasks_path=tmp_path / "snapshot" / "tasks",
        path=tmp_path / "snapshot",
        spec=SimpleNamespace(revision="a" * 40),
    )
    return source_job, snapshot


async def test_exactly_three_patch_and_oracle_attempts_even_after_failure(
    tmp_path, inputs, monkeypatch
):
    module = load_script()
    source_job, snapshot = inputs
    monkeypatch.setattr(module, "fetch_source", lambda *args: snapshot)
    patch = AsyncMock(
        side_effect=[
            {"verified": True, "replay_reward": 0},
            {"verified": True, "replay_reward": 1},
            {"verified": True, "replay_reward": 1},
        ]
    )
    oracle = AsyncMock(
        side_effect=[
            RuntimeError("do-not-echo-secret-body"),
            {"verified": True, "original_reward": 1},
            {"verified": True, "original_reward": 1},
        ]
    )
    monkeypatch.setattr(module, "replay_official_trial", patch)
    monkeypatch.setattr(module, "run_official_trial", oracle)
    output = tmp_path / "diagnostic"
    result = await module.verify(tmp_path / "cache", source_job, output)
    assert patch.await_count == oracle.await_count == 3
    assert result["recorded"] == result["planned"] == 6
    assert result["groups"]["patch"]["observed_score_variation"] is True
    assert result["groups"]["oracle"]["unconfirmed"] == 1
    assert "do-not-echo-secret" not in (output / "records.json").read_text()
    assert read_json(output / "oracle-1.json")["error_type"] == "RuntimeError"
    assert result["original_scores_unchanged"] is True


async def test_final_tasks_are_never_opened_as_calibration(tmp_path, inputs, monkeypatch):
    module = load_script()
    source_job, _ = inputs
    manifest = source_job.parent.parent / "manifest.json"
    write_json(manifest, {"phase": "holdout", "benchmark": "swe-bench-pro-v2"})
    fetch = AsyncMock()
    monkeypatch.setattr(module, "fetch_source", fetch)
    with pytest.raises(ValueError, match="校准题"):
        await module.verify(tmp_path / "cache", source_job, tmp_path / "diagnostic")
    assert fetch.call_count == 0


async def test_existing_diagnostics_cannot_be_overwritten(tmp_path, inputs, monkeypatch):
    module = load_script()
    source_job, snapshot = inputs
    monkeypatch.setattr(module, "fetch_source", lambda *args: snapshot)
    output = tmp_path / "diagnostic"
    output.mkdir()
    with pytest.raises(FileExistsError):
        await module.verify(tmp_path / "cache", source_job, output)
