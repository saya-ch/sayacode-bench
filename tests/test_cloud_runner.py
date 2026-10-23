"""宿主磁盘准备只允许指定的短期 VM，不能影响本机或任务镜像。"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from scripts import prepare_cloud_runner as runner


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch: Any) -> Path:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
        "GITHUB_REPOSITORY": "saya-ch/sayacode-bench-runs",
        "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    return tmp_path


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        ("RUNNER_OS", "Windows"),
        ("GITHUB_REPOSITORY", "saya-ch/sayacode-bench"),
    ],
)
def test_other_hosts_refused_before_writing(
    hosted: Path, monkeypatch: Any, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        runner.prepare(hosted / "evidence.json")
    assert not (hosted / "evidence.json").exists()


def test_actual_windows_cannot_be_enabled_by_environment(hosted: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(ValueError):
        runner.prepare(hosted / "evidence.json")


def test_output_cannot_escape_temporary_directory(hosted: Path) -> None:
    with pytest.raises(ValueError):
        runner.prepare(hosted.parent / "outside.json")
    assert not (hosted.parent / "outside.json").exists()


def test_only_named_toolchains_removed_and_actual_space_recorded(
    hosted: Path, monkeypatch: Any
) -> None:
    android, dotnet = hosted / "android", hosted / "dotnet"
    android.mkdir()
    dotnet.mkdir()
    monkeypatch.setattr(runner, "PREINSTALLED_TOOLCHAINS", (android, dotnet))
    calls = []

    def remove(arguments: list[str], **kwargs: Any) -> None:
        assert arguments[:4] == ["sudo", "rm", "-rf", "--"]
        assert kwargs["check"] is True
        calls.append(arguments[-1])
        Path(arguments[-1]).rmdir()

    monkeypatch.setattr(subprocess, "run", remove)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=123456))
    output = hosted / "evidence/runner.json"
    result = runner.prepare(output)
    assert result["passed"] is True
    assert calls == [str(android), str(dotnet)]
    assert result["free_before_bytes"] == result["free_after_bytes"] == 123456
    assert all(row["removed"] for row in result["targets"])
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_removal_failure_leaves_partial_evidence(hosted: Path, monkeypatch: Any) -> None:
    target = hosted / "android"
    target.mkdir()
    monkeypatch.setattr(runner, "PREINSTALLED_TOOLCHAINS", (target,))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("host preparation failed")

    monkeypatch.setattr(subprocess, "run", fail)
    output = hosted / "evidence.json"
    with pytest.raises(OSError):
        runner.prepare(output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["passed"] is False
    assert saved["targets"][0]["removed"] is False
    assert saved["free_after_bytes"] > 0


def test_every_cloud_job_prepares_before_any_image_input() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/cloud-calibration.yml"
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    for job in jobs.values():
        text = "\n".join(step.get("run", "") for step in job["steps"])
        assert text.index("prepare_cloud_runner.py") < text.index("calibrate_cloud.py dry")
        assert "docker system prune" not in text
    assert tuple(path.as_posix() for path in runner.PREINSTALLED_TOOLCHAINS) == (
        "/usr/local/lib/android",
        "/usr/share/dotnet",
    )


def test_public_controls_use_same_prepare_helper_and_private_default_stays_closed(
    hosted: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "saya-ch/sayacode-bench")
    monkeypatch.setattr(runner, "PREINSTALLED_TOOLCHAINS", ())
    with pytest.raises(ValueError):
        runner.prepare(hosted / "default-refused.json")
    result = runner.prepare(hosted / "public.json", controls_only=True)
    assert result["repository"] == "saya-ch/sayacode-bench"
    assert result["controls_only"] is True
    assert result["role"] == "public_official_controls_host_preparation"
    assert result["passed"] is True


def test_private_repo_cannot_impersonate_public_controls(hosted: Path) -> None:
    with pytest.raises(ValueError):
        runner.prepare(hosted / "wrong-role.json", controls_only=True)
    assert not (hosted / "wrong-role.json").exists()
