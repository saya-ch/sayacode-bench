"""资源核验与三态比较的纯回归，不创建容器，不读取模型或环境凭据。"""

from copy import deepcopy

import pytest
from resource_samples import runtime_evidence

from sayacode_bench.resources import compare_runtimes, resource_status, runtime_record_issues

TASK = {"environment": {"cpus": 1, "memory_mb": 4096}}


def test_complete_evidence_confirms_task_docker_and_cgroup_without_mutation():
    source = runtime_evidence()
    before = deepcopy(source)
    assert resource_status(source, TASK["environment"]) is True
    assert compare_runtimes(source, deepcopy(source), TASK["environment"]) == {
        "same_image": True,
        "same_platform": True,
        "same_resources": True,
    }
    assert source == before


@pytest.mark.parametrize(
    "section,key",
    [
        (None, "requested"),
        (None, "cgroup_v2"),
        ("requested", "cpus"),
        ("requested", "memory_mb"),
        ("docker_limits", "MemorySwap"),
        ("cgroup_v2", "cpu.max"),
        ("cgroup_v2", "memory.max"),
        ("cgroup_v2", "memory.swap.max"),
    ],
)
def test_missing_resource_evidence_stays_unknown(section, key):
    source = runtime_evidence()
    (source if section is None else source[section]).pop(key)
    assert resource_status(source, TASK["environment"]) is None
    assert (
        compare_runtimes(source, runtime_evidence(), TASK["environment"])["same_resources"] is None
    )


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("requested", "cpus", 2),
        ("requested", "memory_mb", 2048),
        ("requested", "cpus", True),
        ("docker_limits", "NanoCpus", 0),
        ("docker_limits", "NanoCpus", 2_000_000_000),
        ("docker_limits", "Memory", 0),
        ("docker_limits", "Memory", 2 * 1024**3),
        ("docker_limits", "MemorySwap", -1),
        ("docker_limits", "MemorySwap", 0),
        ("cgroup_v2", "cpu.max", "max 100000"),
        ("cgroup_v2", "cpu.max", "200000 100000"),
        ("cgroup_v2", "memory.max", "max"),
        ("cgroup_v2", "memory.max", "2147483648"),
        ("cgroup_v2", "memory.swap.max", "max"),
        ("cgroup_v2", "memory.swap.max", "0"),
    ],
)
def test_unlimited_mismatched_and_invalid_limits_cannot_be_confirmed(section, key, value):
    source = runtime_evidence()
    source[section][key] = value
    assert resource_status(source, TASK["environment"]) is False
    assert (
        compare_runtimes(source, deepcopy(source), TASK["environment"])["same_resources"] is False
    )


def test_explicit_zero_swap_is_finite_but_differs_from_frozen_qualification():
    source = runtime_evidence()
    source["docker_limits"]["MemorySwap"] = 4 * 1024**3
    source["cgroup_v2"]["memory.swap.max"] = "0"
    assert resource_status(source, TASK["environment"]) is True
    assert (
        compare_runtimes(source, runtime_evidence(), TASK["environment"])["same_resources"] is False
    )


def test_docker_quota_period_cpu_mode_is_checked_and_configuration_drift_is_visible():
    source = runtime_evidence()
    source["docker_limits"].update(NanoCpus=0, CpuPeriod=100000, CpuQuota=100000)
    assert resource_status(source, TASK["environment"]) is True
    assert compare_runtimes(source, deepcopy(source), TASK["environment"])["same_resources"] is True
    assert (
        compare_runtimes(source, runtime_evidence(), TASK["environment"])["same_resources"] is False
    )


@pytest.mark.parametrize("declaration", [None, {}])
def test_missing_task_resource_declaration_cannot_be_inferred_in_formal_validation(declaration):
    assert resource_status(runtime_evidence(), declaration) is None


@pytest.mark.parametrize("field", ["runtime_identity", "replay_runtime_identity"])
def test_record_comparison_recomputes_source_and_replay_instead_of_trusting_saved_flags(field):
    record = {
        "runtime_identity": runtime_evidence(),
        "replay_runtime_identity": runtime_evidence(),
        "runtime_comparison": {"same_image": True, "same_platform": True, "same_resources": True},
    }
    assert runtime_record_issues(record, TASK, runtime_evidence(), replay=True) == []
    record[field]["docker_limits"]["Memory"] = 0
    issues = runtime_record_issues(record, TASK, runtime_evidence(), replay=True)
    assert any("same_resources_mismatch" in issue for issue in issues)


def test_missing_qualification_or_pristine_does_not_match_by_accident():
    assert runtime_record_issues({"runtime_identity": runtime_evidence()}, TASK, None, replay=True)
