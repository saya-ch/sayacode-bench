"""固定资格规则、机械替补、上限与精确恢复；全部使用离线官方 Job 边界。"""

import hashlib
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.task.id import LocalTaskId
from harbor.models.trial.config import AgentConfig, TaskConfig, TrialConfig
from harbor.models.trial.result import AgentInfo, TrialResult
from harbor.models.verifier.result import VerifierResult
from resource_samples import runtime_evidence

from sayacode_bench.artifacts import read_json, write_json
from sayacode_bench.execution import normalize_trial_result
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


def native_result(task_id, reward, root, *, name="oracle", repeat=1, runtime=True):
    job = root / f"{task_id}-{name}-{repeat}"
    directory = job / "native-trial"
    task_path = root / "tasks" / task_id
    now = datetime.now(UTC)
    trial = TrialResult(
        task_name=task_id,
        trial_name=directory.name,
        trial_uri=directory.as_uri(),
        task_id=LocalTaskId(path=task_path),
        task_checksum="offline-fixture-only",
        config=TrialConfig(task=TaskConfig(path=task_path), agent=AgentConfig(name=name)),
        agent_info=AgentInfo(name=name, version="offline"),
        agent_result=AgentContext(),
        verifier_result=VerifierResult(rewards={"reward": reward}),
        started_at=now,
        finished_at=now + timedelta(seconds=1),
    )
    write_json(directory / "result.json", trial.model_dump(mode="json"))
    observation = runtime_evidence(image_id=f"sha256:{task_id}")
    observation["available"] = runtime
    observation["requested"]["memory_mb"] = 2048
    observation["docker_limits"].update(Memory=2048 * 1024**2, MemorySwap=4096 * 1024**2)
    observation["cgroup_v2"].update(
        {"memory.max": str(2048 * 1024**2), "memory.swap.max": str(2048 * 1024**2)}
    )
    write_json(directory / "runtime.json", observation)
    row = normalize_trial_result(
        trial, directory, configuration=name, repeat=repeat, endpoint="local"
    )
    row.update(job_dir=str(job), request_sha256=hashlib.sha256(str(job).encode()).hexdigest())
    return row


def refresh_native(row):
    """改动合成原生工件后重新规范化，避免只测试保存布尔值。"""
    path = Path(row["raw_trial_result"]["path"])
    trial = TrialResult.model_validate(read_json(path))
    original = {key: row[key] for key in ("job_dir", "request_sha256")}
    row.update(
        normalize_trial_result(
            trial,
            path.parent,
            configuration=row["configuration"],
            repeat=row["repeat"],
            endpoint="local",
        )
    )
    row.update(original)


def change_runtime(row, transform):
    path = Path(row["runtime"]["path"])
    observation = read_json(path)
    transform(observation)
    write_json(path, observation)
    refresh_native(row)


def install_runner(monkeypatch, loaded, *, failed_task=None, raise_first=False, mutate=None):
    async def run(path, output, name, agent, environment, **kwargs):
        if agent.name == "oracle" and path.name == failed_task and kwargs["repeat"] == 1:
            if raise_first:
                raise RuntimeError("private-error-body")
            reward = 0
        else:
            reward = 1 if agent.name == "oracle" else 0
        row = native_result(
            path.name, reward, output / "mock", name=agent.name, repeat=kwargs["repeat"]
        )
        # 模拟原生 runner 的固定 job 身份与磁盘布局。
        destination = output / name
        source = Path(row["job_dir"])
        source.rename(destination)
        trial_path = destination / "native-trial" / "result.json"
        trial = TrialResult.model_validate(read_json(trial_path))
        row = normalize_trial_result(
            trial,
            trial_path.parent,
            configuration=agent.name,
            repeat=kwargs["repeat"],
            endpoint="local",
        )
        row.update(
            job_dir=str(destination), request_sha256=hashlib.sha256(name.encode()).hexdigest()
        )
        if mutate:
            mutate(row)
        write_json(destination / "normalized.json", row)
        return row

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


async def test_failed_fixture_finishes_fixed_trials_then_replaces_entire_group(
    tmp_path, monkeypatch
):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    failed = initial["dev"][0]["task_id"]
    runner = install_runner(monkeypatch, loaded, failed_task=failed)
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
    assert "private-error-body" not in (output / "sanity.json").read_text(encoding="utf-8")


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


def test_unconfirmed_or_drifting_runtime_cannot_qualify_even_with_good_rewards(tmp_path):
    loaded = module()
    task = catalog()[0]
    oracle = [native_result(task.task_id, 1, tmp_path, repeat=index) for index in range(1, 4)]
    nop = native_result(task.task_id, 0, tmp_path, name="nop", runtime=False)
    result = loaded.grade_qualification(task, oracle, nop, 3)
    assert result["passed"] is False
    assert "native_runtime_evidence_unconfirmed" in result["reasons"]
    nop = native_result(task.task_id, 0, tmp_path, name="nop")
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


async def test_infrastructure_exception_stops_cohort_without_replacement_or_retry(
    tmp_path, monkeypatch
):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    failed = initial["dev"][0]["task_id"]
    runner = install_runner(monkeypatch, loaded, failed_task=failed, raise_first=True)
    output = tmp_path / "out"
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert runner.await_count == 1
    assert result["complete"] is result["passed"] is False
    assert result["qualification"]["reason"] == "qualification_execution_unconfirmed"
    assert result["qualification"]["rejected"] == []
    assert result["qualification"]["incomplete"] == [failed]
    assert len(list((output / "selections").glob("selection-*.json"))) == 1
    runner.reset_mock()
    resumed = await loaded.qualify(source, tmp_path / "cache", output)
    assert resumed["complete"] is False and runner.await_count == 0
    assert "private-error-body" not in (output / "sanity.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "kind", ["task_memory", "cpu_unlimited", "memory_unlimited", "swap_unlimited", "cgroup_missing"]
)
def test_same_wrong_or_unknown_resources_are_incomplete_not_fixture_failure(tmp_path, kind):
    loaded = module()
    task = catalog()[0]
    oracle = [native_result(task.task_id, 1, tmp_path, repeat=index) for index in range(1, 4)]
    nop = native_result(task.task_id, 0, tmp_path, name="nop")

    def change(value):
        if kind == "task_memory":
            value["requested"]["memory_mb"] = 4096
            value["docker_limits"].update(Memory=4096 * 1024**2, MemorySwap=8192 * 1024**2)
            value["cgroup_v2"].update(
                {"memory.max": str(4096 * 1024**2), "memory.swap.max": str(4096 * 1024**2)}
            )
        elif kind == "cpu_unlimited":
            value["docker_limits"]["NanoCpus"] = 0
            value["cgroup_v2"]["cpu.max"] = "max 100000"
        elif kind == "memory_unlimited":
            value["docker_limits"]["Memory"] = 0
            value["cgroup_v2"]["memory.max"] = "max"
        elif kind == "swap_unlimited":
            value["docker_limits"]["MemorySwap"] = -1
            value["cgroup_v2"]["memory.swap.max"] = "max"
        else:
            value.pop("cgroup_v2")

    for row in [*oracle, nop]:
        change_runtime(row, change)
    result = loaded.grade_qualification(task, oracle, nop, 3)
    assert result["complete"] is result["passed"] is result["continuation_allowed"] is False
    assert "native_runtime_evidence_unconfirmed" in result["reasons"]
    assert "reference_not_accepted_in_every_fixed_trial" not in result["reasons"]


@pytest.mark.parametrize(
    "kind", ["resource", "missing_native", "unfinished", "infrastructure_error"]
)
async def test_unconfirmed_control_stops_before_remaining_controls(tmp_path, monkeypatch, kind):
    loaded, source, _ = setup(monkeypatch, tmp_path)

    def mutate(row):
        if kind == "resource":
            change_runtime(row, lambda value: value.pop("cgroup_v2"))
        elif kind == "missing_native":
            Path(row["raw_trial_result"]["path"]).unlink()
        elif kind == "unfinished":
            path = Path(row["raw_trial_result"]["path"])
            value = read_json(path)
            value["finished_at"] = None
            write_json(path, value)
            refresh_native(row)
        else:
            row.update(status="infrastructure_error", verified=False, success=False)

    runner = install_runner(monkeypatch, loaded, mutate=mutate)
    result = await loaded.qualify(source, tmp_path / "cache", tmp_path / "out")
    assert runner.await_count == 1
    assert result["complete"] is False
    assert result["qualification"]["rejected"] == []
    assert len(result["tasks"][0]["oracle_trials"]) == 1


async def test_single_control_batches_resume_same_plan_without_repeating_or_changing_three_plus_one(
    tmp_path, monkeypatch
):
    loaded, source, initial = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    plan_bytes = None
    for count in range(1, 9):
        result = await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
        assert runner.await_count == count
        if plan_bytes is None:
            plan_bytes = (output / "plan.json").read_bytes()
        assert (output / "plan.json").read_bytes() == plan_bytes
        assert result["qualification"]["rejected"] == []
        assert read_json(output / "selection.json")["dev"] == initial["dev"]
        if count < 8:
            assert result["complete"] is False
            assert result["qualification"]["reason"] == "control_batch_limit_reached"
    assert result["complete"] is result["passed"] is True
    assert [(call.args[3].name, call.kwargs["repeat"]) for call in runner.call_args_list] == [
        ("oracle", 1),
        ("oracle", 2),
        ("oracle", 3),
        ("nop", 1),
    ] * 2
    assert len({call.args[2] for call in runner.call_args_list}) == 8


async def test_batch_cap_can_change_without_changing_fixed_plan(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    result = await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=7)
    assert result["complete"] is True and runner.await_count == 8


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
async def test_invalid_batch_cap_rejected_before_native_job(tmp_path, monkeypatch, limit):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    with pytest.raises(ValueError, match="正整数"):
        await loaded.qualify(source, tmp_path / "cache", tmp_path / "out", max_new_controls=limit)
    assert not runner.call_args_list


async def test_saved_complete_native_is_recovered_without_replaying_after_wrapper_gap(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    qualification = next((output / "qualifications").iterdir())
    first = read_json(qualification / "oracle-1.json")["record"]
    (qualification / "oracle-1.json").unlink()
    (qualification / "qualification.json").unlink()
    result = await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    assert result["complete"] is False and runner.await_count == 2
    assert read_json(qualification / "oracle-1.json")["record"] == first
    assert runner.call_args_list[1].kwargs["repeat"] == 2


async def test_attempt_with_unconfirmed_native_job_is_preserved_and_never_replayed(
    tmp_path, monkeypatch
):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    qualification = next((output / "qualifications").iterdir())
    first = read_json(qualification / "oracle-1.json")["record"]
    (qualification / "oracle-1.json").unlink()
    (qualification / "qualification.json").unlink()
    (Path(first["job_dir"]) / "normalized.json").unlink()
    runner.reset_mock()
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert result["complete"] is False and runner.await_count == 0
    assert result["qualification"]["rejected"] == []
    assert read_json(qualification / "oracle-1.json")["record"]["status"] == "qualification_unknown"


async def test_completed_summary_cannot_hide_changed_native_evidence(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    first = await loaded.qualify(source, tmp_path / "cache", output)
    assert first["passed"] is True
    native = Path(first["tasks"][0]["oracle"]["raw_trial_result"]["path"])
    native.write_text("{}", encoding="utf-8")
    runner.reset_mock()
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert result["complete"] is False and runner.await_count == 0
    assert result["qualification"]["rejected"] == []


async def test_existing_job_without_attempt_identity_is_unknown_not_replayed(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    qualification = next((output / "qualifications").iterdir())
    attempt = read_json(qualification / "oracle-1.attempt.json")
    orphan = Path(attempt["job_dir"].replace("oracle-1", "oracle-2"))
    orphan.mkdir()
    runner.reset_mock()
    result = await loaded.qualify(source, tmp_path / "cache", output)
    assert result["complete"] is False and runner.await_count == 0
    assert result["qualification"]["rejected"] == []
    assert read_json(qualification / "oracle-2.json")["record"]["status"] == "qualification_unknown"


async def test_saved_control_cannot_point_at_another_native_job(tmp_path, monkeypatch):
    loaded, source, _ = setup(monkeypatch, tmp_path)
    runner = install_runner(monkeypatch, loaded)
    output = tmp_path / "out"
    await loaded.qualify(source, tmp_path / "cache", output, max_new_controls=1)
    qualification = next((output / "qualifications").iterdir())
    path = qualification / "oracle-1.json"
    saved = read_json(path)
    saved["record"]["job_dir"] += "-other"
    write_json(path, saved)
    runner.reset_mock()
    with pytest.raises(ValueError, match="job"):
        await loaded.qualify(source, tmp_path / "cache", output)
    assert runner.await_count == 0
