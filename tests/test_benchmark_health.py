"""题库体检器的定位测试：trial 目录按内容识别，不依赖 ``instance_`` 前缀。

背景：2026-11-07 复盘 S1 —— 体检器用 ``startswith("instance_")`` 找 trial 目录，
接入 SWE-EVO（``sweevo-...__xxx``）后**静默输出空表**，看起来像「没有任何失败」。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import benchmark_health as module

INSTANCE_TRIAL = "instance_repo__proj-abc123__aB3dEf"
SWEEVO_TRIAL = "sweevo-dask-dask-2022-9-2__R2jYLdj"


def make_job(
    root: Path,
    agent: str,
    task: str,
    repeat: int,
    trial_name: str,
    tests: list[dict[str, str]],
) -> Path:
    job = root / agent / "jobs" / f"{agent}-{task}-r{repeat}"
    trial = job / trial_name
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier" / "output.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
    return job


@pytest.mark.parametrize("trial_name", [INSTANCE_TRIAL, SWEEVO_TRIAL])
def test_collect_finds_failed_tests_for_both_namings(tmp_path: Path, trial_name: str) -> None:
    make_job(
        tmp_path,
        "sayacode",
        "task-abc123",
        1,
        trial_name,
        [
            {"name": "test_a", "status": "FAILED"},
            {"name": "test_b", "status": "PASSED"},
        ],
    )

    per_task = module.collect([tmp_path])

    assert "task-abc123" in per_task, "非 instance_ 命名的 trial 不能被静默跳过"
    assert per_task["task-abc123"]["sayacode"] == [{"test_a"}]


@pytest.mark.parametrize("trial_name", [INSTANCE_TRIAL, SWEEVO_TRIAL])
def test_collect_ignores_jobs_without_output(tmp_path: Path, trial_name: str) -> None:
    job = make_job(
        tmp_path, "mini-swe", "task-xyz", 1, trial_name, [{"name": "t", "status": "FAILED"}]
    )
    (job / trial_name / "verifier" / "output.json").unlink()

    assert module.collect([tmp_path]) == {}


def test_collect_dedupes_repeated_job_names(tmp_path: Path) -> None:
    """jobs/ 与 verify/jobs/ 各有一份产物时，同一 (agent, task, repeat) 只记一次。"""
    make_job(
        tmp_path, "sayacode", "task-dup", 1, SWEEVO_TRIAL, [{"name": "t1", "status": "FAILED"}]
    )
    verify_trial = (
        tmp_path / "sayacode" / "verify" / "jobs" / "verify-sayacode-task-dup-r1" / SWEEVO_TRIAL
    )
    (verify_trial / "verifier").mkdir(parents=True)
    (verify_trial / "verifier" / "output.json").write_text(
        json.dumps({"tests": [{"name": "t1", "status": "FAILED"}]}), encoding="utf-8"
    )

    per_task = module.collect([tmp_path])

    assert len(per_task["task-dup"]["sayacode"]) == 1
