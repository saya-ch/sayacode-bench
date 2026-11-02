"""CI 冒烟门禁脚本的单元测试；dry-run 不触碰模型与真实产物。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ci_smoke


def write_sample(path: Path, count: int = 3) -> Path:
    tasks = [
        {"task_id": f"instance_repo__proj-{index:04d}", "repo": "repo"} for index in range(count)
    ]
    path.write_text(
        json.dumps({"schema_version": 1, "size": count, "tasks": tasks}), encoding="utf-8"
    )
    return path


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    for name in ("TASKS_ROOT", "PROFILE", "WHEEL", "REQUIREMENTS", "VARIANT"):
        monkeypatch.setenv(f"SAYACODE_BENCH_{name}", str(missing / name.lower()))
    monkeypatch.setenv("SAYACODE_BENCH_SMOKE_OUT", str(tmp_path / "smoke"))


def test_load_sample_tasks_requires_two(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "s.json", count=1)
    with pytest.raises(ValueError):
        ci_smoke.load_sample_tasks(sample)
    assert len(ci_smoke.load_sample_tasks(write_sample(tmp_path / "ok.json", 3))) == 3


def test_select_smoke_tasks_deterministic(tmp_path: Path) -> None:
    tasks = ci_smoke.load_sample_tasks(write_sample(tmp_path / "s.json", 10))
    first = ci_smoke.select_smoke_tasks(tasks)
    second = ci_smoke.select_smoke_tasks(tasks)
    assert [task["task_id"] for task in first] == [task["task_id"] for task in second]
    assert len(first) == 2
    with pytest.raises(ValueError):
        ci_smoke.select_smoke_tasks(tasks, count=11)


def test_smoke_job_name() -> None:
    assert ci_smoke.smoke_job_name("instance_a__b-123") == "smoke-sayacode-a__b-123-r1"


def test_structure_checks_pass(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "s.json", 5)
    tasks = ci_smoke.load_sample_tasks(sample)
    selected = ci_smoke.select_smoke_tasks(tasks)
    checks = ci_smoke.structure_checks(sample, tasks, tmp_path / "out", selected)
    assert all(check.status == ci_smoke.PASS for check in checks), [
        check.as_dict() for check in checks
    ]


def test_main_dry_run_ok_with_skipped_runtime(tmp_path: Path, isolated_env: None) -> None:
    sample = write_sample(tmp_path / "s.json", 5)
    out_json = tmp_path / "report.json"
    code = ci_smoke.main(
        [
            "--sample",
            str(sample),
            "--out",
            str(tmp_path / "smoke"),
            "--no-docker",
            "--json-out",
            str(out_json),
        ]
    )
    assert code == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["status"] == "ok"
    assert payload["model_requests"] == 0
    skipped = {check["name"] for check in payload["checks"] if check["status"] == "skipped"}
    assert {"tasks_root", "sayacode_inputs", "docker"} <= skipped


def test_main_require_runtime_turns_skips_into_failures(tmp_path: Path, isolated_env: None) -> None:
    sample = write_sample(tmp_path / "s.json", 5)
    code = ci_smoke.main(
        [
            "--sample",
            str(sample),
            "--out",
            str(tmp_path / "smoke"),
            "--no-docker",
            "--require-runtime",
        ]
    )
    assert code == 1


def test_main_execute_refuses_when_runtime_missing(tmp_path: Path, isolated_env: None) -> None:
    sample = write_sample(tmp_path / "s.json", 5)
    code = ci_smoke.main(
        ["--sample", str(sample), "--out", str(tmp_path / "smoke"), "--no-docker", "--execute"]
    )
    assert code == 1


def test_validate_trial_checks(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "job"
    inner = job / "instance_x__y"
    (inner / "agent").mkdir(parents=True)
    (inner / "agent" / "model.patch").write_bytes(b"diff --git a b\n")
    passed = ci_smoke.validate_trial({"status": "completed", "original_reward": 1.0}, job)
    assert [check.status for check in passed] == [ci_smoke.PASS] * 3

    failed = ci_smoke.validate_trial({"status": "exception:Timeout", "original_reward": None}, job)
    assert [check.status for check in failed] == [ci_smoke.FAIL, ci_smoke.FAIL, ci_smoke.PASS]

    (inner / "agent" / "model.patch").write_bytes(b"")
    empty = ci_smoke.validate_trial({"status": "completed", "original_reward": 0.0}, job)
    assert empty[-1].status == ci_smoke.FAIL
