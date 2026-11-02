"""对账脚本的单元测试；fixture 全部是临时目录，不是真实成绩。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import reconcile_results


def job_name(agent: str, task_id: str, repeat: int) -> str:
    return reconcile_results.planned_job_name(agent, task_id, repeat)


def make_real_job(root: Path, agent: str, task_id: str, repeat: int, reward: float | None) -> Path:
    job = root / agent / "jobs" / job_name(agent, task_id, repeat)
    inner = job / f"instance_{task_id.replace('instance_', '')[:18]}__x"
    (inner / "verifier").mkdir(parents=True)
    if reward is not None:
        (inner / "verifier" / "reward.txt").write_text(str(reward), encoding="utf-8")
    return job


TASK_A = "instance_repo__proj-0001"
TASK_B = "instance_repo__proj-0002"


def good_summary() -> dict:
    return {
        "schema_version": 2,
        "sample": {"size": 2},
        "repeats": 2,
        "agents": {
            "sayacode": {
                "planned": 4,
                "observed": 3,
                "passes": 2,
                "missing": 1,
                "missing_trials": [
                    {
                        "task_id": TASK_B,
                        "repeat": 2,
                        "class": "empty_patch",
                        "job": job_name("sayacode", TASK_B, 2),
                    }
                ],
                "trials": [
                    {
                        "task_id": TASK_A,
                        "repeat": 1,
                        "job": job_name("sayacode", TASK_A, 1),
                        "kind": "native",
                        "reward": 1.0,
                    },
                    {
                        "task_id": TASK_A,
                        "repeat": 2,
                        "job": job_name("sayacode", TASK_A, 2),
                        "kind": "native",
                        "reward": 1.0,
                    },
                    {
                        "task_id": TASK_B,
                        "repeat": 1,
                        "job": job_name("sayacode", TASK_B, 1),
                        "kind": "native",
                        "reward": 0.0,
                    },
                    {
                        "task_id": TASK_B,
                        "repeat": 2,
                        "job": None,
                        "kind": None,
                        "reward": None,
                        "class": "empty_patch",
                    },
                ],
            },
            "mini-swe": {
                "planned": 4,
                "observed": 4,
                "passes": 3,
                "missing": 0,
                "missing_trials": [],
                "trials": [
                    {
                        "task_id": TASK_A,
                        "repeat": 1,
                        "job": job_name("mini-swe", TASK_A, 1),
                        "kind": "native",
                        "reward": 1.0,
                    },
                    {
                        "task_id": TASK_A,
                        "repeat": 2,
                        "job": job_name("mini-swe", TASK_A, 2),
                        "kind": "native",
                        "reward": 0.0,
                    },
                    {
                        "task_id": TASK_B,
                        "repeat": 1,
                        "job": job_name("mini-swe", TASK_B, 1),
                        "kind": "native",
                        "reward": 1.0,
                    },
                    {
                        "task_id": TASK_B,
                        "repeat": 2,
                        "job": job_name("mini-swe", TASK_B, 2),
                        "kind": "native",
                        "reward": 1.0,
                    },
                ],
            },
        },
        "totals": {"planned": 8, "observed": 7, "passes": 5, "missing": 1},
    }


def build_disk(root: Path) -> None:
    for agent, rewards in (
        ("sayacode", [(TASK_A, 1, 1.0), (TASK_A, 2, 1.0), (TASK_B, 1, 0.0)]),
        ("mini-swe", [(TASK_A, 1, 1.0), (TASK_A, 2, 0.0), (TASK_B, 1, 1.0), (TASK_B, 2, 1.0)]),
    ):
        for task_id, repeat, reward in rewards:
            make_real_job(root, agent, task_id, repeat, reward)
    # empty_patch：目录存在但没有 reward.txt
    make_real_job(root, "sayacode", TASK_B, 2, None)


def test_good_fixture_is_consistent(tmp_path: Path) -> None:
    build_disk(tmp_path)
    issues = reconcile_results.reconcile_root(tmp_path, good_summary())
    assert issues == []


def test_missing_job_directory_reported(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["mini-swe"]["trials"][0]["job"] = "mini-swe-does-not-exist-r1"
    codes = [issue.code for issue in reconcile_results.reconcile_root(tmp_path, summary)]
    assert "no_job" in codes


def test_reward_mismatch_reported(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["sayacode"]["trials"][0]["reward"] = 0.0  # 磁盘是 1.0
    codes = [issue.code for issue in reconcile_results.reconcile_root(tmp_path, summary)]
    assert "reward_mismatch" in codes


def test_planned_denominator_reported(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["sayacode"]["planned"] = 5
    codes = [issue.code for issue in reconcile_results.reconcile_root(tmp_path, summary)]
    assert "planned_denominator" in codes
    assert "denominator_split" in codes


def test_invalid_missing_class_reported(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["sayacode"]["missing_trials"][0]["class"] = "weird"
    codes = [issue.code for issue in reconcile_results.reconcile_root(tmp_path, summary)]
    assert "missing_class_invalid" in codes


def test_no_job_class_with_existing_directory(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["sayacode"]["missing_trials"][0] = {
        "task_id": TASK_B,
        "repeat": 1,
        "class": "no_job",
        "job": None,
    }
    codes = [issue.code for issue in reconcile_results.reconcile_root(tmp_path, summary)]
    assert "missing_job_inconsistent" in codes


def test_cli_strict_returns_nonzero(tmp_path: Path) -> None:
    build_disk(tmp_path)
    summary = good_summary()
    summary["agents"]["sayacode"]["trials"][0]["reward"] = 0.0
    summary_path = tmp_path / "FINAL-SUMMARY.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    assert reconcile_results.main(["--root", str(tmp_path), "--dry-run", "--strict"]) == 1
    assert reconcile_results.main(["--root", str(tmp_path), "--dry-run"]) == 0
