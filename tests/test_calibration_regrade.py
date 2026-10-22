"""真实校准补丁的便携来源、固定重判序列及最小公开产物。"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench.artifacts import file_sha256, read_json, write_json

_UPSTREAM = """from pathlib import Path
class PatchReplayAgent:
    def __init__(self, *args, source_job, patch_name="model.patch", **kwargs):
        self._source_job = Path(source_job)
        self._patch_name = patch_name
    async def setup(self, environment): pass
    async def run(self, instruction, environment, context): pass
    def version(self): return "1.0.0"
"""


def module() -> Any:
    path = Path(__file__).parents[1] / "scripts" / "regrade_calibration_patches.py"
    spec = importlib.util.spec_from_file_location("calibration_regrade_script", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: Any) -> Any:
    script = module()
    source = tmp_path / "source"
    tooling = source / "v2" / "tooling" / "patch_replay.py"
    tooling.parent.mkdir(parents=True)
    tooling.write_text(_UPSTREAM, encoding="utf-8")
    monkeypatch.setattr(script, "TOOLING_SHA256", file_sha256(tooling))
    evidence = tmp_path / "evidence"
    fixtures = []
    for fixture in script.FIXTURES:
        directory = evidence / fixture["name"]
        directory.mkdir(parents=True)
        patch = directory / "model.patch"
        patch.write_text(f"DO-NOT-PUBLISH-PATCH-{fixture['name']}", encoding="utf-8")
        (directory / "LICENSE").write_text("公开许可", encoding="utf-8")
        fixture = {**fixture, "patch_sha256": file_sha256(patch)}
        fixtures.append(fixture)
        write_json(
            directory / "source.json",
            {
                "schema_version": 1,
                "phase": "calibration_patch_evidence",
                "source_kind": "actual_captured_model_patch",
                "benchmark": "swe-bench-pro-v2",
                "revision": script.REVISION,
                "task_id": fixture["task_id"],
                "patch_sha256": fixture["patch_sha256"],
                "patch_bytes": patch.stat().st_size,
                "original_reward": 0.0,
                "local_pristine_reward": 0.0,
                "original_raw_trial_result_sha256": "a" * 64,
                "original_worker_result_sha256": "b" * 64,
                "original_records_sha256": "c" * 64,
                "immutable_image_digest": fixture["digest"],
                "license_sha256": file_sha256(directory / "LICENSE"),
                "private_unrecognized_body": {"message": "DO-NOT-PUBLISH-PRIVATE-BODY"},
            },
        )
    monkeypatch.setattr(script, "FIXTURES", tuple(fixtures))
    for fixture in script.fixed_plan()["fixtures"]:
        task = source / "v2" / "tasks" / fixture["task_id"]
        task.mkdir(parents=True)
        (task / "task.toml").write_text(
            "[environment]\ncpus=1\nmemory_mb=4096\nstorage_mb=10240\n"
            f'docker_image="{fixture["original_image_reference"]}"\n',
            encoding="utf-8",
        )
    snapshot = SimpleNamespace(
        path=source,
        tasks_path=source / "v2" / "tasks",
        spec=SimpleNamespace(revision=script.REVISION),
    )
    monkeypatch.setattr(script, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(script, "version", lambda *args: "0.24.0")
    monkeypatch.setattr(
        script,
        "prior_qutebrowser_controls",
        lambda: script.fixed_plan()["prior_qutebrowser_controls"],
    )

    async def pin(fixture: dict[str, Any]) -> dict[str, Any]:
        return {
            "expected_image_id": "sha256:" + "d" * 64,
            "expected_repo_digest": fixture["immutable_image"],
        }

    monkeypatch.setattr(script, "pin_image", pin)
    calls = []

    async def execute(
        task: Path,
        raw: Path,
        name: str,
        agent: dict[str, Any],
        environment: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append({"agent": agent, "environment": environment, **kwargs})
        is_patch = "import_path" in agent
        if is_patch:
            portable = Path(agent["kwargs"]["source_job"])
            assert not list(portable.rglob("result.json"))
            assert not list(portable.rglob("normalized.json"))
            plugin = importlib.import_module("sayacode_bench.artifact_replay")
            replay = plugin.ArtifactReplayAgent(source_job=str(portable))
            assert replay._find_patch(task.name).is_file()
        fixture = next(
            item for item in script.fixed_plan()["fixtures"] if item["task_id"] == task.name
        )
        trial = raw / name / "instance_fake__trial"
        reward = 0 if agent.get("name") == "nop" or (is_patch and kwargs["repeat"] == 2) else 1
        write_json(
            trial / "result.json",
            {
                "task_name": task.name,
                "verifier_result": {"rewards": {"reward": reward}},
                "exception_info": None,
            },
        )
        write_json(
            trial / "runtime.json",
            {
                "available": True,
                "image_id": "sha256:" + "d" * 64,
                "repo_digests": [fixture["immutable_image"]],
            },
        )
        (trial / "agent").mkdir()
        if is_patch:
            write_json(
                trial / "agent" / "replay.json",
                {
                    "task": task.name,
                    "patch": str(portable),
                    "apply_rc": 0,
                    "apply_out": "DO-NOT-PUBLISH-APPLICATION-OUTPUT",
                },
            )
        (trial / "agent" / "solution.log").write_text("DO-NOT-PUBLISH-SOLUTION", encoding="utf-8")
        verifier = trial / "verifier"
        verifier.mkdir()
        (verifier / "test-stdout.txt").write_text(
            "Required tests: 10\nPassed tests: 9\nTypeError: DO-NOT-PUBLISH-ASSERTION\n",
            encoding="utf-8",
        )
        return {
            "job_dir": str(raw / name),
            "status": "completed",
            "original_reward": reward,
            "verified": True,
        }

    monkeypatch.setattr(script, "run_official_trial", execute)
    return SimpleNamespace(
        script=script,
        snapshot=snapshot,
        evidence=evidence,
        cache=tmp_path / "cache",
        output=tmp_path / "output",
        calls=calls,
    )


def test_plan_fixes_six_patch_repeats_four_controls_and_upstream_tooling_identity() -> None:
    script = module()
    plan = script.fixed_plan()
    assert [item["name"] for item in plan["fixtures"]] == ["qutebrowser", "ansible"]
    assert len(plan["schedule"]) == 10
    assert [item["agent"] for item in plan["schedule"]] == ["portable-patch-replay"] * 3 + [
        "oracle"
    ] * 3 + ["nop"] + ["portable-patch-replay"] * 3
    assert [item["repeat"] for item in plan["schedule"]] == [1, 2, 3, 1, 2, 3, 1, 1, 2, 3]
    assert plan["prior_qutebrowser_controls"]["same_vm_as_current_patch_trials"] is False
    assert plan["prior_qutebrowser_controls"]["workflow_url"].endswith("39736698121")
    assert (
        plan["upstream_tooling_sha256"]
        == "5c8b344de37164e9723f1724c2573013957fb644c3913a64c12c1718c737d876"
    )
    assert "only _find_patch" in plan["replay_adaptation"]
    assert plan["formal_comparison_eligible"] is False
    assert plan["affects_local_scores"] is False
    assert plan["model_requests"] == 0


def test_prior_qutebrowser_controls_bind_published_native_evidence() -> None:
    reference = module().prior_qutebrowser_controls()
    assert len(reference["files_sha256"]) == 4
    assert len(reference["runtime_files_sha256"]) == 4
    assert reference["oracle_rewards"] == [1, 1, 1] and reference["nop_rewards"] == [0]
    assert reference["same_vm_as_current_patch_trials"] is False


def test_portable_locator_inherits_upstream_run_setup_and_checks_identity(scenario: Any) -> None:
    script = scenario.script
    fixture = script.fixed_plan()["fixtures"][0]
    portable = scenario.output / "portable"
    script.prepare_source(scenario.evidence, fixture, portable)
    with script.replay_tooling(scenario.snapshot):
        official = importlib.import_module("patch_replay").PatchReplayAgent
        adapted = importlib.import_module("sayacode_bench.artifact_replay").ArtifactReplayAgent
        assert adapted.run is official.run and adapted.setup is official.setup
        assert set(adapted.__dict__) - {
            "__module__",
            "__doc__",
            "__firstlineno__",
            "__static_attributes__",
        } == {"_find_patch"}
        instance = adapted(source_job=str(portable / fixture["name"]))
        patch = instance._find_patch(fixture["task_id"])
        assert file_sha256(patch) == fixture["patch_sha256"]
        with pytest.raises(ValueError, match="身份不匹配"):
            instance._find_patch("another-task")
        patch.write_text("changed", encoding="utf-8")
        with pytest.raises(ValueError, match="字节"):
            instance._find_patch(fixture["task_id"])


def test_tooling_import_is_hash_checked_restored_and_creates_no_bytecode(scenario: Any) -> None:
    prior = {
        name: sys.modules.get(name) for name in ("patch_replay", "sayacode_bench.artifact_replay")
    }
    bytecode = sys.dont_write_bytecode
    with scenario.script.replay_tooling(scenario.snapshot) as identity:
        assert identity["artifact_locator_sha256"]
        assert sys.dont_write_bytecode is bytecode
    assert all(sys.modules.get(name) is value for name, value in prior.items())
    assert not list(scenario.snapshot.path.rglob("*.pyc"))
    module_path = scenario.snapshot.path / "v2" / "tooling" / "patch_replay.py"
    module_path.write_text("raise RuntimeError('must never run')", encoding="utf-8")
    with pytest.raises(ValueError, match="Git blob"):
        with scenario.script.replay_tooling(scenario.snapshot):
            pytest.fail("不应导入已变化的上游源码")


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "wrong-task"),
        ("revision", "f" * 40),
        ("patch_sha256", "f" * 64),
        ("patch_bytes", 0),
        ("immutable_image_digest", "sha256:" + "0" * 64),
        ("original_raw_trial_result_sha256", "missing"),
        ("original_reward", None),
    ],
)
def test_mismatched_source_is_rejected_without_faking_native_results(
    scenario: Any, field: str, value: Any
) -> None:
    fixture = scenario.script.fixed_plan()["fixtures"][0]
    source = scenario.evidence / fixture["name"] / "source.json"
    write_json(source, {**read_json(source), field: value})
    with pytest.raises(ValueError):
        scenario.script.prepare_source(scenario.evidence, fixture, scenario.output)
    assert not list(scenario.evidence.rglob("result.json"))


async def test_all_ten_run_even_with_zero_reward_and_public_artifacts_exclude_raw_content(
    scenario: Any,
) -> None:
    before = {path: file_sha256(path) for path in scenario.evidence.rglob("*") if path.is_file()}
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert len(scenario.calls) == 10
    assert result["all_jobs_attempted"] and result["all_expected_images_confirmed"]
    assert result["all_native_trials_scored"] and result["all_replay_evidence_available"]
    assert result["ansible_controls_passed"] and result["all_patches_applied"]
    assert result["fixtures"]["ansible"]["oracle_rewards"] == [1, 1, 1]
    assert result["fixtures"]["ansible"]["nop_rewards"] == [0]
    assert all(item["cloud_pristine_rewards"] == [1, 0, 1] for item in result["fixtures"].values())
    patches = [call for call in scenario.calls if "import_path" in call["agent"]]
    assert len(patches) == 6 and all(
        call["agent"]["import_path"] == scenario.script.PLUGIN for call in patches
    )
    assert sum(call["agent"] == {"name": "oracle"} for call in scenario.calls) == 3
    assert sum(call["agent"] == {"name": "nop"} for call in scenario.calls) == 1
    assert all(call["canonical_model"] == call["endpoint"] == "not_used" for call in scenario.calls)
    assert all(
        call["environment"]["kwargs"] == {"messages_upstream": "http://127.0.0.1:9/v1/messages"}
        for call in scenario.calls
    )
    public = scenario.output / "public"
    artifacts = [path for path in public.rglob("*") if path.is_file()]
    text = "\n".join(path.read_text(encoding="utf-8") for path in artifacts)
    assert "DO-NOT-PUBLISH" not in text
    assert str(scenario.output) not in text
    assert not any(path.suffix == ".patch" or "solution" in path.name for path in artifacts)
    assert len(list(public.glob("trials/*/runtime.json"))) == 10
    assert len(list(public.glob("trials/*/native-result-observations.json"))) == 10
    assert len(list(public.glob("trials/*/replay-observations.json"))) == 6
    assert all(file_sha256(path) == digest for path, digest in before.items())
    for path in public.glob("sources/*.json"):
        source = read_json(path)
        assert source["original_reward"] == source["local_pristine_reward"] == 0
        assert "private_unrecognized_body" not in source


async def test_execution_failure_keeps_fixed_later_jobs(scenario: Any, monkeypatch: Any) -> None:
    original = scenario.script.run_official_trial
    count = 0

    async def run(*args: Any, **kwargs: Any) -> Any:
        nonlocal count
        count += 1
        if count == 1:
            raise OSError("DO-NOT-PUBLISH-ERROR")
        return await original(*args, **kwargs)

    monkeypatch.setattr(scenario.script, "run_official_trial", run)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert count == 10 and result["recorded_jobs"] == 10
    records = read_json(scenario.output / "public" / "summary.json")
    assert records["all_expected_images_confirmed"] is False


async def test_image_failure_is_not_attempted_and_does_not_skip_other_fixture(
    scenario: Any, monkeypatch: Any
) -> None:
    original = scenario.script.pin_image

    async def pin(fixture: dict[str, Any]) -> Any:
        if fixture["name"] == "qutebrowser":
            raise OSError("image unavailable")
        return await original(fixture)

    monkeypatch.setattr(scenario.script, "pin_image", pin)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert result["recorded_jobs"] == 10 and len(scenario.calls) == 7
    assert result["all_jobs_attempted"] is False
    assert result["fixtures"]["qutebrowser"]["statuses"] == ["preparation_failed"] * 3


async def test_source_failure_preserves_ten_not_attempted_items(
    scenario: Any, monkeypatch: Any
) -> None:
    def fail(*args: Any) -> Any:
        raise OSError("download unavailable")

    monkeypatch.setattr(scenario.script, "fetch_source", fail)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert result["recorded_jobs"] == 10 and not scenario.calls
    assert result["all_jobs_attempted"] is False


async def test_cancel_preserves_partial_evidence_and_does_not_fake_remaining_failures(
    scenario: Any, monkeypatch: Any
) -> None:
    original = scenario.script.run_official_trial

    async def run(*args: Any, **kwargs: Any) -> Any:
        if args[2] == "calibration-1-portable-patch-replay-2":
            raise asyncio.CancelledError()
        return await original(*args, **kwargs)

    monkeypatch.setattr(scenario.script, "run_official_trial", run)
    with pytest.raises(asyncio.CancelledError):
        await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    result = read_json(scenario.output / "public" / "summary.json")
    assert result["interrupted"] and result["recorded_jobs"] == 1


async def test_existing_output_is_not_resumed(scenario: Any) -> None:
    scenario.output.mkdir()
    with pytest.raises(FileExistsError):
        await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)


def test_empty_patch_observation_preserves_official_no_apply_semantics(tmp_path: Path) -> None:
    script = module()
    job = tmp_path / "job"
    write_json(job / "instance_test" / "agent" / "replay.json", {"task": "test", "patch": None})
    result = script.replay_observations({"job_dir": str(job)}, tmp_path, "test")
    assert result["empty_or_missing_patch"] is True
    assert result["patch_applied_attempted"] is False
    assert result["apply_rc"] is None and result["native_replay_sha256"]


def test_replay_artifact_cannot_be_from_another_task(tmp_path: Path) -> None:
    script = module()
    job = tmp_path / "job"
    write_json(
        job / "instance_test" / "agent" / "replay.json", {"task": "another-task", "patch": None}
    )
    with pytest.raises(ValueError, match="任务身份"):
        script.replay_observations({"job_dir": str(job)}, tmp_path, "test")


def test_known_source_fields_reject_nested_private_body(scenario: Any) -> None:
    fixture = scenario.script.fixed_plan()["fixtures"][0]
    source = scenario.evidence / fixture["name"] / "source.json"
    write_json(source, {**read_json(source), "canonical_model": {"api_key": "private"}})
    with pytest.raises(ValueError, match="标量"):
        scenario.script.prepare_source(scenario.evidence, fixture, scenario.output)


async def test_missing_replay_evidence_does_not_hide_rewards_or_claim_evidence_complete(
    scenario: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        scenario.script,
        "replay_observations",
        lambda *args: {"available": False, "reason": "missing"},
    )
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert result["all_jobs_attempted"] and result["all_native_trials_scored"]
    assert result["all_replay_evidence_available"] is False
    assert len(scenario.calls) == 10


async def test_evidence_collection_error_keeps_native_score_for_all_ten(
    scenario: Any, monkeypatch: Any
) -> None:
    def fail(*args: Any) -> Any:
        raise OSError("DO-NOT-PUBLISH-PRIVATE-PATH")

    monkeypatch.setattr(scenario.script, "collect_trial", fail)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert result["recorded_jobs"] == len(scenario.calls) == 10
    assert result["all_native_trials_scored"] is False
    assert result["all_expected_images_confirmed"] is False
    assert result["fixtures"]["qutebrowser"]["cloud_pristine_rewards"] == [1, 0, 1]


async def test_missing_patch_source_does_not_skip_independent_ansible_controls(
    scenario: Any,
) -> None:
    (scenario.evidence / "ansible" / "model.patch").unlink()
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert len(scenario.calls) == 7 and result["recorded_jobs"] == 10
    assert result["ansible_controls_passed"] is True
    assert result["fixtures"]["ansible"]["cloud_pristine_rewards"] == [None] * 3


async def test_failed_reference_control_does_not_selectively_skip_patch_trials(
    scenario: Any, monkeypatch: Any
) -> None:
    original = scenario.script.run_official_trial

    async def run(*args: Any, **kwargs: Any) -> Any:
        raw = await original(*args, **kwargs)
        if args[3].get("name") == "oracle" and kwargs["repeat"] == 2:
            raw["original_reward"] = 0
            native = next(Path(raw["job_dir"]).glob("instance_*/result.json"))
            write_json(native, {**read_json(native), "verifier_result": {"rewards": {"reward": 0}}})
        return raw

    monkeypatch.setattr(scenario.script, "run_official_trial", run)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert len(scenario.calls) == 10 and result["all_native_trials_scored"]
    assert result["ansible_controls_passed"] is False
    assert result["fixtures"]["ansible"]["oracle_rewards"] == [1, 0, 1]
    assert result["fixtures"]["ansible"]["cloud_pristine_rewards"] == [1, 0, 1]


async def test_apply_failure_is_explicit_separate_from_evidence_completeness(
    scenario: Any, monkeypatch: Any
) -> None:
    original = scenario.script.replay_observations

    def observe(*args: Any) -> Any:
        return {**original(*args), "apply_rc": 1}

    monkeypatch.setattr(scenario.script, "replay_observations", observe)
    result = await scenario.script.regrade(scenario.cache, scenario.output, scenario.evidence)
    assert len(scenario.calls) == 10 and result["all_replay_evidence_available"]
    assert result["all_patches_applied"] is False


@pytest.mark.parametrize("task,reward", [("another-task", 0), ("test", 1)])
def test_native_trial_task_or_normalized_score_mismatch_is_rejected(
    tmp_path: Path, task: str, reward: int
) -> None:
    script = module()
    job = tmp_path / "job"
    write_json(
        job / "instance_test" / "result.json",
        {"task_name": task, "verifier_result": {"rewards": {"reward": reward}}},
    )
    with pytest.raises(ValueError):
        script.native_result_observations(
            {"job_dir": str(job), "original_reward": 0}, tmp_path, "test"
        )


def test_main_returns_error_when_only_attempts_and_images_are_known(
    monkeypatch: Any, tmp_path: Path
) -> None:
    script = module()

    async def regrade(*args: Any) -> Any:
        return {
            "all_jobs_attempted": True,
            "all_expected_images_confirmed": True,
            "all_native_trials_scored": True,
            "all_replay_evidence_available": False,
            "ansible_controls_passed": True,
        }

    monkeypatch.setattr(script, "regrade", regrade)
    monkeypatch.setattr(
        sys,
        "argv",
        ["regrade", "--cache", str(tmp_path / "cache"), "--output", str(tmp_path / "output")],
    )
    assert script.main() == 1


def test_workflow_is_manual_no_model_secrets_and_only_uploads_public_evidence() -> None:
    path = Path(__file__).parents[1] / ".github" / "workflows" / "calibration-regrade.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    job = workflow["jobs"]["calibration-regrade"]
    assert job["timeout-minutes"] == "30"
    assert workflow["permissions"] == {"contents": "read"}
    uploads = [step for step in job["steps"] if "upload-artifact" in step.get("uses", "")]
    assert len(uploads) == 1 and uploads[0]["with"]["path"].endswith("/calibration-regrade/public/")
    assert uploads[0]["if"] == "always()"
    assert "secrets." not in text and "api_key" not in text
    assert "-m scripts.regrade_calibration_patches" in text
