"""正式资格必须有三次参考解与一次空解，旧单次预检不能晋升。"""

from copy import deepcopy
from pathlib import Path

import pytest

from sayacode_bench.artifacts import file_sha256
from sayacode_bench.gates import validate_preflight


def evidence():
    task = {
        "task_id": "task-a",
        "instruction_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "task_tree_sha256": "c" * 64,
    }
    trials = []
    for index in range(4):
        oracle = index < 3
        trials.append(
            {
                "task_id": task["task_id"],
                "configuration": "oracle" if oracle else "nop",
                "repeat": index + 1 if oracle else 1,
                "record_complete": True,
                "status": "completed",
                "verified": True,
                "success": oracle,
                "original_reward": int(oracle),
                "request_sha256": f"{index + 1:064x}",
                "raw_trial_result": {"sha256": f"{index + 11:064x}"},
                "runtime": {"sha256": f"{index + 21:064x}"},
                "runtime_identity": {
                    "available": True,
                    "image_id": "sha256:" + "a" * 64,
                    "architecture": "amd64",
                    "os": "linux",
                    "requested": {"cpus": 1, "memory_mb": 4096},
                    "docker_limits": {"NanoCpus": 1_000_000_000, "Memory": 4 * 1024**3},
                },
            }
        )
    gate = {
        "benchmark": "fixture",
        "revision": "revision",
        "complete": True,
        "passed": True,
        "tasks": [
            {
                **task,
                "passed": True,
                "oracle_repeats": 3,
                "oracle": deepcopy(trials[0]),
                "oracle_trials": trials[:3],
                "nop": trials[3],
            }
        ],
    }
    probe = {
        "passed": True,
        "cleanup_confirmed": True,
        "source_sha256": {
            "network.py": file_sha256(Path(__file__).parents[1] / "src/sayacode_bench/network.py")
        },
    }
    return task, gate, probe


def validate(task, gate, probe):
    validate_preflight(gate, probe, benchmark="fixture", revision="revision", tasks=[task])


def test_fixed_independent_three_plus_one_with_matching_runtime_is_accepted():
    validate(*evidence())


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_wrong_reference_count_is_rejected_even_when_summary_says_passed(count):
    task, gate, probe = evidence()
    row = gate["tasks"][0]
    row["oracle_trials"] = (row["oracle_trials"] * 2)[:count]
    row["oracle_repeats"] = count
    with pytest.raises(ValueError, match="固定三次"):
        validate(task, gate, probe)


def test_legacy_single_sanity_result_cannot_be_used_as_formal_preflight():
    task, gate, probe = evidence()
    del gate["tasks"][0]["oracle_trials"]
    del gate["tasks"][0]["oracle_repeats"]
    with pytest.raises(ValueError, match="固定三次"):
        validate(task, gate, probe)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "other"),
        ("configuration", "oracle"),
        ("repeat", 2),
        ("record_complete", False),
        ("status", "timeout"),
        ("verified", False),
        ("success", True),
        ("original_reward", 1),
    ],
)
def test_native_empty_control_facts_are_rechecked(field, value):
    task, gate, probe = evidence()
    gate["tasks"][0]["nop"][field] = value
    with pytest.raises(ValueError, match="状态或官方评分"):
        validate(task, gate, probe)


def test_reference_failure_is_not_hidden_by_passed_true():
    task, gate, probe = evidence()
    gate["tasks"][0]["oracle_trials"][2].update(success=False, original_reward=0)
    with pytest.raises(ValueError, match="状态或官方评分"):
        validate(task, gate, probe)


@pytest.mark.parametrize("field", ["request_sha256", "raw_trial_result"])
def test_reusing_a_native_trial_does_not_count_as_another_repeat(field):
    task, gate, probe = evidence()
    trials = gate["tasks"][0]["oracle_trials"]
    trials[1][field] = deepcopy(trials[0][field])
    with pytest.raises(ValueError, match="四次独立"):
        validate(task, gate, probe)


@pytest.mark.parametrize("field", ["image_id", "architecture", "requested", "docker_limits"])
def test_runtime_platform_and_resource_drift_in_one_control_is_rejected(field):
    task, gate, probe = evidence()
    runtime = gate["tasks"][0]["nop"]["runtime_identity"]
    runtime[field] = {"changed": 1} if isinstance(runtime[field], dict) else "changed"
    with pytest.raises(ValueError, match="资源不一致"):
        validate(task, gate, probe)


@pytest.mark.parametrize("field", ["raw_trial_result", "runtime"])
def test_missing_native_artifact_identity_cannot_be_promoted(field):
    task, gate, probe = evidence()
    gate["tasks"][0]["nop"].pop(field)
    with pytest.raises(ValueError, match="工件哈希"):
        validate(task, gate, probe)


def test_qualified_first_oracle_used_for_freeze_must_match_fixed_trials():
    task, gate, probe = evidence()
    gate["tasks"][0]["oracle"]["runtime_identity"]["image_id"] = "other-image"
    with pytest.raises(ValueError, match="固定三次"):
        validate(task, gate, probe)
