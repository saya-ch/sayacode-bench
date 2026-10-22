"""固定资格规则、机械替补、上限与精确恢复；全部使用离线官方 Job 边界。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sayacode_bench.artifacts import read_json, write_json
from sayacode_bench.selection import select_tasks
from sayacode_bench.sources import SOURCES, TaskRecord


def module():
    source = Path(__file__).parents[1] / "scripts" / "qualify_fixtures.py"
    spec = importlib.util.spec_from_file_location("qualify_script", source)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def catalog(count=6, benchmark="swe-bench-pro-v2"):
    return [
        TaskRecord(
            benchmark=benchmark,
            revision=SOURCES[benchmark].revision,
            task_id=f"fixture-{index}",
            task_name=f"fixture-{index}",
            repository=f"repository-{index % 2}",
            language="python",
            category="debugging",
            difficulty="medium",
            leakage_group=f"fix-{index}",
            instruction_sha256="a" * 64,
            config_sha256="b" * 64,
            task_tree_sha256="c" * 64,
            agent={"timeout_sec": 900},
            verifier={"timeout_sec": 900},
            environment={"memory_mb": 2048, "cpus": 1, "docker_image": f"public/{index}"},
        )
        for index in range(count)
    ]


def setup(monkeypatch, tmp_path, *, tasks=None, dev=1, final=1):
    loaded = module()
    tasks = tasks or catalog()
    initial = select_tasks(tasks, dev_count=dev, holdout_count=final, seed="frozen").public_dict()
    source = tmp_path / "initial.json"
    write_json(source, initial)
    snapshot = SimpleNamespace(tasks_path=tmp_path / "snapshot", spec=SOURCES[tasks[0].benchmark])
    monkeypatch.setattr(loaded, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(loaded, "build_catalog", lambda *args: tasks)
    monkeypatch.setattr(loaded, "implementation_identity", lambda: {"source": "frozen"})
    monkeypatch.setattr(loaded.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3))
    return loaded, source, initial


def native_result(task_id, reward, *, runtime=True):
    return {
        "task_id": task_id,
        "status": "completed",
        "verified": True,
        "original_reward": reward,
        "success": reward == 1,
        "runtime_identity": {
            "available": runtime,
            "image_id": f"sha256:{task_id}",
            "architecture": "amd64",
            "os": "linux",
            "docker_limits": {"Memory": 2048},
            "requested": {"memory_mb": 2048},
        },
    }


def install_runner(monkeypatch, loaded, *, failed_task=None, raise_first=False):
    async def run(path, output, name, agent, environment, **kwargs):
        if agent.name == "oracle" and path.name == failed_task and kwargs["repeat"] == 1:
            if raise_first:
                raise RuntimeError("private-error-body")
            reward = 0
        else:
            reward = 1 if agent.name == "oracle" else 0
        return native_result(path.name, reward)

    mock = AsyncMock(side_effect=run)
    monkeypatch.setattr(loaded, "run_official_trial", mock)
    return mock


async def test_every_selected_task_gets_exact_three_reference_and_one_empty_trials(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert result["complete"] is result["passed"] is True
    assert runner.await_count == 8
    assert sum(call.args[3].name == "oracle" for call in runner.call_args_list) == 6
    assert all(len(task["oracle_trials"]) == 3 for task in result["tasks"])
    assert (tmp_path / "out" / "selection.json").is_file()
    assert read_json(tmp_path / "out" / "plan.json")["max_candidates"] == 64


@pytest.mark.parametrize("raise_first", [False, True])
async def test_failed_fixture_finishes_fixed_trials_then_replaces_entire_group(
    tmp_path, monkeypatch, raise_first
):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    failed = initial["dev"][0]["task_id"]
    runner = install_runner(monkeypatch, loaded, failed_task=failed, raise_first=raise_first)
    output = tmp_path / "out"
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert result["complete"] is True
    assert sum(call.args[0].name == failed for call in runner.call_args_list) == 4
    assert runner.await_count == 12
    selected = read_json(output / "selection.json")
    assert failed not in {task["task_id"] for task in selected["dev"] + selected["holdout"]}
    assert any(row["reason"] == "fixture_qualification_failed" for row in selected["exclusions"])
    assert len(list((output / "selections").glob("selection-*.json"))) == 2
    assert result["qualification"]["checked_candidates"] == 3
    assert "private-error-body" not in (output / "sanity.json").read_text()


async def test_budget_exhaustion_is_incomplete_without_silent_sample_reduction(
    tmp_path, monkeypatch
):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded, failed_task=initial["dev"][0]["task_id"])
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out", max_candidates=2)
    assert result["complete"] is result["passed"] is False
    assert result["qualification"]["reason"] == "candidate_budget_exhausted"
    assert result["qualification"]["planned_dev"] == result["qualification"]["planned_holdout"] == 1
    assert runner.await_count == 8


async def test_low_disk_stops_before_job_and_does_not_reject_unexecuted_fixture(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    monkeypatch.setattr(
        loaded.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=loaded.MIN_DISK_HEADROOM_BYTES - 1),
    )
    output = tmp_path / "out"
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert runner.await_count == 0
    assert result["complete"] is result["passed"] is False
    assert result["qualification"]["reason"] == "insufficient_disk_headroom"
    assert result["qualification"]["checked_candidates"] == 0
    assert result["qualification"]["rejected"] == []
    assert result["tasks"] == []
    assert read_json(output / "plan.json")["min_disk_headroom_bytes"] == 12 * 1024**3


async def test_complete_resume_does_not_repeat_native_jobs(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    first = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    runner.reset_mock()
    second = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert second == first
    assert runner.await_count == 0


async def test_interrupted_version_resumes_saved_candidate_without_repeating_its_trials(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    save = loaded.save_outcome
    monkeypatch.setattr(
        loaded,
        "save_outcome",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("interrupt after saved qualification")
        ),
    )
    with pytest.raises(RuntimeError, match="interrupt"):
        await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert runner.await_count == 4
    runner.reset_mock()
    monkeypatch.setattr(loaded, "save_outcome", save)
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert result["complete"] is True
    assert runner.await_count == 4


async def test_changed_input_cannot_resume_or_overwrite_previous_plan(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    runner.reset_mock()
    with source.open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="完全相同"):
        await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert runner.await_count == 0


async def test_resume_finishes_saved_selection_before_drawing_reserves(tmp_path, monkeypatch):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    first_id = initial["dev"][0]["task_id"]
    next_id = initial["holdout"][0]["task_id"]
    runner = install_runner(monkeypatch, loaded, failed_task=first_id)
    save = loaded.save_outcome
    monkeypatch.setattr(
        loaded,
        "save_outcome",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("saved failed candidate")),
    )
    with pytest.raises(RuntimeError, match="saved failed"):
        await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert runner.await_count == 4
    runner.reset_mock()
    monkeypatch.setattr(loaded, "save_outcome", save)
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert result["complete"] is True
    assert runner.call_args_list[0].args[0].name == next_id
    assert all(call.args[0].name != first_id for call in runner.call_args_list)


def test_unconfirmed_or_drifting_runtime_cannot_qualify_even_with_good_rewards():
    loaded = module()
    task = catalog()[0]
    oracle = [native_result(task.task_id, 1) for _ in range(3)]
    nop = native_result(task.task_id, 0, runtime=False)
    result = loaded.grade_qualification(task, oracle, nop, 3)
    assert result["passed"] is False
    assert "native_runtime_evidence_unconfirmed" in result["reasons"]
    nop = native_result(task.task_id, 0)
    nop["runtime_identity"]["image_id"] = "sha256:other"
    assert (
        "native_runtime_identity_changed"
        in loaded.grade_qualification(task, oracle, nop, 3)["reasons"]
    )


async def test_terminal_secondary_counts_come_from_selection_not_swe_constants(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(
        monkeypatch, tmp_path, tasks=catalog(16, "terminal-bench-2.1"), dev=2, final=12
    )
    runner = install_runner(monkeypatch, loaded)
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert result["complete"] is True
    assert result["benchmark"] == "terminal-bench-2.1"
    assert runner.await_count == 56
    assert result["qualification"]["planned_dev"] == 2
    assert result["qualification"]["planned_holdout"] == 12
