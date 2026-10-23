"""正式准备读取全部三十二题原生文件；合成工件不是公开基准成绩。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_fixture_qualification import catalog, native_result

from sayacode_bench.artifacts import file_sha256
from sayacode_bench.sources import SOURCES
from scripts import prepare_primary_study as module
from scripts import qualify_fixtures

COHORT = {"ImageOS": "synthetic-ubuntu24", "ImageVersion": "offline-v1", "RUNNER_ARCH": "X64"}


@pytest.fixture
def qualified(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    tasks = catalog(32)
    rows = []
    for task in tasks:
        oracle = [
            native_result(task.task_id, 1, tmp_path, name="oracle", repeat=index)
            for index in (1, 2, 3)
        ]
        nop = native_result(task.task_id, 0, tmp_path, name="nop")
        checked = qualify_fixtures.grade_qualification(task, oracle, nop, 3)
        assert checked["complete"] is checked["passed"] is True
        rows.append(checked)
    selection = {
        "dev": [task.public_dict() for task in tasks[:8]],
        "holdout": [task.public_dict() for task in tasks[8:]],
    }
    gate = {
        "benchmark": "swe-bench-pro-v2",
        "revision": SOURCES["swe-bench-pro-v2"].revision,
        "complete": True,
        "passed": True,
        "tasks": rows,
        "qualification_host_cohort": dict(COHORT),
        "qualification_host_scope": {
            "execution_repository": "saya-ch/sayacode-bench",
            "public_source_sha": module.QUALIFICATION_SOURCE,
            "cloud_plan_sha256": "d" * 64,
            "host_cohort_scope": ["ImageOS", "ImageVersion", "RUNNER_ARCH"],
            "host_cohort_exclusions": [
                "physical_cpu_identity",
                "kernel_identity",
                "provider_model_immutability",
            ],
            "host_hardware_boundary": "只核验托管镜像声明，不声明硬件相同",
        },
    }
    probe = {
        "passed": True,
        "cleanup_confirmed": True,
        "source_sha256": {"network.py": file_sha256(module.ROOT / "src/sayacode_bench/network.py")},
    }

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("准备阶段不得新建控制试验或模型运行")

    monkeypatch.setattr(qualify_fixtures, "run_official_trial", forbidden)
    return SimpleNamespace(selection=selection, gate=gate, probe=probe, root=tmp_path)


def verify(qualified: SimpleNamespace) -> None:
    module.verify_primary_qualification(
        qualified.selection, qualified.gate, qualified.probe, COHORT
    )


def test_all_128_native_controls_are_reopened_without_changing_original_files(
    qualified: SimpleNamespace,
    monkeypatch: Any,
) -> None:
    before = {path: file_sha256(path) for path in qualified.root.rglob("*.json")}
    calls = []
    original = module.control_issues

    def observed(task: Any, record: dict[str, Any], name: str, repeat: int) -> list[str]:
        calls.append((task.task_id, name, repeat))
        return original(task, record, name, repeat)

    monkeypatch.setattr(module, "control_issues", observed)
    verify(qualified)
    assert len(calls) == len(set(calls)) == 128
    assert {task for task, _, _ in calls} == {
        task["task_id"] for task in [*qualified.selection["dev"], *qualified.selection["holdout"]]
    }
    assert before == {path: file_sha256(path) for path in qualified.root.rglob("*.json")}


def test_top_level_passed_flags_do_not_replace_holdout_qualification(
    qualified: SimpleNamespace,
) -> None:
    qualified.gate["tasks"] = qualified.gate["tasks"][:9]
    assert qualified.gate["complete"] is qualified.gate["passed"] is True
    with pytest.raises(ValueError, match="三十二个唯一任务"):
        verify(qualified)


@pytest.mark.parametrize("task_index", [8, 31])
@pytest.mark.parametrize("field", ["raw_trial_result", "runtime"])
def test_missing_holdout_native_file_blocks_preparation_even_with_valid_summary(
    qualified: SimpleNamespace,
    task_index: int,
    field: str,
) -> None:
    trial = qualified.gate["tasks"][task_index]["oracle_trials"][2]
    Path(trial[field]["path"]).unlink()
    assert qualified.gate["tasks"][task_index]["passed"] is True
    with pytest.raises(ValueError, match="原生资格原件未确认"):
        verify(qualified)


def test_changed_holdout_nop_original_cannot_hide_behind_unchanged_hash_declaration(
    qualified: SimpleNamespace,
) -> None:
    original = Path(qualified.gate["tasks"][-1]["nop"]["raw_trial_result"]["path"])
    original.write_text(original.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="原生资格原件未确认"):
        verify(qualified)


def test_complete_flags_cannot_hide_failed_holdout_control(qualified: SimpleNamespace) -> None:
    qualified.gate["tasks"][-1]["oracle_trials"][2].update(success=False, original_reward=0)
    with pytest.raises(ValueError, match="官方评分未确认"):
        verify(qualified)


def test_same_task_in_dev_and_holdout_is_not_counted_as_32(qualified: SimpleNamespace) -> None:
    qualified.selection["holdout"][0] = deepcopy(qualified.selection["dev"][0])
    with pytest.raises(ValueError, match="三十二个唯一任务"):
        verify(qualified)


def test_previous_qualification_source_remains_fixed(qualified: SimpleNamespace) -> None:
    qualified.gate["qualification_host_scope"]["public_source_sha"] = "b" * 40
    with pytest.raises(ValueError, match="完整原定三十二题资格"):
        verify(qualified)
