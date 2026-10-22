"""抽样的可重复性、资源边界和开发/验收隔离检查。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sayacode_bench.selection import select_tasks, write_manifest
from sayacode_bench.sources import TaskRecord


def _task(index: int, repository: str = "example/repo", **updates: object) -> TaskRecord:
    task = TaskRecord(
        benchmark="swe-bench-pro-v2",
        revision="a" * 40,
        task_id=f"task-{index}",
        task_name=f"task-{index}",
        repository=repository,
        language="python",
        category="debugging",
        difficulty="medium",
        leakage_group=f"{repository}:{index}",
        instruction_sha256="b" * 64,
        config_sha256="c" * 64,
        task_tree_sha256="d" * 64,
        agent={"timeout_sec": 3000, "network_mode": "no-network"},
        verifier={"timeout_sec": 3000},
        environment={"cpus": 1, "memory_mb": 4096, "docker_image": "example/task:fixed"},
    )
    return replace(task, **updates)  # type: ignore[arg-type]


def test_selection_is_reproducible_and_order_independent() -> None:
    catalog = [_task(index, f"repo/{index % 3}") for index in range(30)]
    first = select_tasks(catalog, dev_count=6, holdout_count=12, seed="study")
    second = select_tasks(list(reversed(catalog)), dev_count=6, holdout_count=12, seed="study")
    assert first.public_dict() == second.public_dict()
    assert len(first.dev) == 6
    assert len(first.holdout) == 12
    assert {task.repository for task in first.dev} == {task.repository for task in first.holdout}
    assert not {task.task_id for task in first.dev} & {task.task_id for task in first.holdout}
    changed = select_tasks(catalog, dev_count=6, holdout_count=12, seed="another-study")
    assert [task.task_id for task in first.dev] != [task.task_id for task in changed.dev]


def test_variants_of_same_fix_never_cross_splits() -> None:
    catalog = [_task(index) for index in range(10)]
    catalog.append(replace(catalog[0], task_id="duplicate-variant"))
    selection = select_tasks(catalog, dev_count=3, holdout_count=6, seed="study")
    selected = selection.dev + selection.holdout
    assert len({task.leakage_group for task in selected}) == len(selected)
    assert selection.eligible_count == 10
    assert sum(item.reason == "duplicate_fixing_commit_group" for item in selection.exclusions) == 1


def test_calibration_fix_exclusion_removes_every_variant_and_keeps_full_pool_hash() -> None:
    catalog = [_task(index) for index in range(12)]
    catalog.append(replace(catalog[0], task_id="calibration-sibling-version"))
    unfiltered = select_tasks(catalog, dev_count=2, holdout_count=4, seed="study")
    selection = select_tasks(
        catalog,
        dev_count=2,
        holdout_count=4,
        seed="study",
        excluded_leakage_groups=(catalog[0].leakage_group,),
    )
    assert selection.catalog_sha256 == unfiltered.catalog_sha256
    assert selection.eligible_count == 11
    assert all(
        task.leakage_group != catalog[0].leakage_group for task in selection.dev + selection.holdout
    )
    exclusions = [item for item in selection.exclusions if item.reason == "calibration_group"]
    assert {item.task_id for item in exclusions} == {
        catalog[0].task_id,
        "calibration-sibling-version",
    }
    assert selection.rules["excluded_leakage_groups"] == [catalog[0].leakage_group]


def test_benchmark_qualified_calibration_group_does_not_exclude_other_benchmark() -> None:
    swe = _task(20, leakage_group="shared-group")
    terminal = _task(21, benchmark="terminal-bench-2.1", leakage_group="shared-group")
    catalog = [_task(index) for index in range(6)] + [swe, terminal]
    selection = select_tasks(
        catalog,
        dev_count=2,
        holdout_count=5,
        seed="study",
        excluded_leakage_groups=(f"{swe.benchmark}:{swe.leakage_group}",),
    )
    assert len(selection.exclusions) == 1
    assert selection.exclusions[0].task_id == swe.task_id
    assert terminal.task_id in {task.task_id for task in selection.dev + selection.holdout}


def test_calibration_exclusion_is_order_independent_and_unmatched_names_are_visible() -> None:
    catalog = [_task(index) for index in range(12)]
    groups = [catalog[0].leakage_group, catalog[1].leakage_group, "not-in-this-snapshot"]
    first = select_tasks(
        catalog, dev_count=2, holdout_count=4, seed="study", excluded_leakage_groups=groups
    )
    second = select_tasks(
        list(reversed(catalog)),
        dev_count=2,
        holdout_count=4,
        seed="study",
        excluded_leakage_groups=list(reversed(groups)),
    )
    assert first.public_dict() == second.public_dict()
    assert first.rules["unmatched_excluded_leakage_groups"] == ["not-in-this-snapshot"]


@pytest.mark.parametrize("groups", ["not-a-list", [""], [None]])
def test_invalid_calibration_group_collection_is_rejected(groups) -> None:
    with pytest.raises(ValueError, match="excluded_leakage_groups"):
        select_tasks(
            [_task(index) for index in range(6)],
            dev_count=2,
            holdout_count=4,
            seed="study",
            excluded_leakage_groups=groups,
        )


def test_resources_are_preserved_and_infeasible_tasks_are_publicly_excluded() -> None:
    catalog = [_task(index) for index in range(8)]
    catalog.extend(
        [
            _task(8, environment={"cpus": 4, "memory_mb": 8192, "docker_image": "large"}),
            _task(9, environment={"cpus": 1, "memory_mb": 2048, "gpus": 1, "docker_image": "gpu"}),
            _task(
                10,
                environment={"cpus": 1, "memory_mb": 2048, "os": "windows", "docker_image": "win"},
            ),
        ]
    )
    selection = select_tasks(catalog, dev_count=2, holdout_count=4, seed="study")
    assert len(selection.exclusions) == 3
    assert all(
        task.environment == catalog[0].environment for task in selection.dev + selection.holdout
    )
    assert all(task.agent["timeout_sec"] == 3000 for task in selection.dev + selection.holdout)
    assert selection.rules["concurrency"] == 1


def test_language_scope_is_explicit_not_silently_dropped() -> None:
    catalog = [_task(index) for index in range(8)] + [_task(9, language="go")]
    selection = select_tasks(
        catalog, dev_count=2, holdout_count=4, seed="study", languages=("python",)
    )
    assert selection.rules["languages"] == ("python",)
    assert selection.exclusions[0].reason == "outside_predeclared_language_scope"


def test_insufficient_tasks_fail_without_silent_shrink() -> None:
    with pytest.raises(ValueError, match="不足"):
        select_tasks([_task(0)], dev_count=1, holdout_count=1, seed="study")


def test_custom_compose_is_explicitly_excluded_without_modifying_official_environment() -> None:
    compose = _task(9, has_custom_compose=True)
    catalog = [_task(index) for index in range(6)] + [compose]
    manifest = select_tasks(catalog, dev_count=2, holdout_count=4, seed="study")
    assert manifest.eligible_count == 6
    assert len(manifest.exclusions) == 1
    assert manifest.exclusions[0].task_id == compose.task_id
    assert manifest.exclusions[0].reason == "custom_compose_not_supported_by_local_network_protocol"
    assert compose.has_custom_compose is True
    assert all(not task.has_custom_compose for task in manifest.dev + manifest.holdout)


def test_duplicate_task_ids_fail() -> None:
    with pytest.raises(ValueError, match="重复"):
        select_tasks([_task(0), _task(0)], dev_count=1, holdout_count=1, seed="study")


def test_frozen_manifest_cannot_be_overwritten(tmp_path: Path) -> None:
    manifest = select_tasks(
        [_task(i) for i in range(6)], dev_count=2, holdout_count=4, seed="study"
    )
    destination = tmp_path / "study.json"
    digest = write_manifest(manifest, destination)
    assert len(digest) == 64
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert len(payload["dev"]) == 2
    assert "PRIVATE" not in destination.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_manifest(manifest, destination)


def test_terminal_tasks_use_category_strata() -> None:
    catalog = [
        _task(
            index, benchmark="terminal-bench-2.1", category=("debugging" if index % 2 else "system")
        )
        for index in range(16)
    ]
    manifest = select_tasks(catalog, dev_count=4, holdout_count=8, seed="study")
    assert {task.category for task in manifest.dev} == {"debugging", "system"}
    assert {task.category for task in manifest.holdout} == {"debugging", "system"}


def test_category_scope_filters_metadata_and_keeps_entire_catalog_identity() -> None:
    catalog = [
        _task(
            index, benchmark="terminal-bench-2.1", category="debugging", agent={"timeout_sec": 900}
        )
        for index in range(8)
    ] + [
        _task(
            20,
            benchmark="terminal-bench-2.1",
            category="machine-learning",
            agent={"timeout_sec": 900},
        )
    ]
    complete = select_tasks(catalog, dev_count=2, holdout_count=4, seed="fixed")
    selected = select_tasks(
        catalog, dev_count=2, holdout_count=4, seed="fixed", categories=("debugging",)
    )
    assert selected.catalog_sha256 == complete.catalog_sha256
    assert selected.eligible_count == 8
    assert selected.exclusions[0].task_id == "task-20"
    assert selected.exclusions[0].reason == "outside_predeclared_category_scope"
    assert selected.rules["categories"] == ("debugging",)
    assert all(task.category == "debugging" for task in selected.dev + selected.holdout)


def test_official_timeout_scope_is_inclusive_and_does_not_shorten_tasks() -> None:
    catalog = [
        _task(
            index,
            benchmark="terminal-bench-2.1",
            agent={"timeout_sec": 1800.0},
            verifier={"timeout_sec": 3600},
        )
        for index in range(6)
    ] + [_task(20, benchmark="terminal-bench-2.1", agent={"timeout_sec": 1800.1})]
    unfiltered = select_tasks(catalog, dev_count=2, holdout_count=4, seed="fixed")
    selected = select_tasks(
        catalog, dev_count=2, holdout_count=4, seed="fixed", max_agent_timeout_sec=1800
    )
    assert selected.catalog_sha256 == unfiltered.catalog_sha256
    assert selected.exclusions[0].reason == "official_agent_timeout_exceeds_study_scope"
    assert selected.rules["max_agent_timeout_sec"] == 1800
    assert all(task.agent["timeout_sec"] == 1800.0 for task in selected.dev + selected.holdout)
    assert all(task.verifier["timeout_sec"] == 3600 for task in selected.dev + selected.holdout)
    assert catalog[-1].agent["timeout_sec"] == 1800.1


@pytest.mark.parametrize("value", [None, 0, -1, True, float("nan"), "900"])
def test_unknown_official_timeout_is_not_assumed_to_fit_scope(value: object) -> None:
    catalog = [_task(index, agent={"timeout_sec": 900}) for index in range(6)]
    catalog.append(_task(20, agent={"timeout_sec": value}))
    selected = select_tasks(
        catalog, dev_count=2, holdout_count=4, seed="fixed", max_agent_timeout_sec=1800
    )
    assert selected.exclusions[0].reason == "missing_or_invalid_official_agent_timeout"


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_maximum_timeout_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="max_agent_timeout_sec"):
        select_tasks(
            [_task(i) for i in range(6)],
            dev_count=2,
            holdout_count=4,
            seed="fixed",
            max_agent_timeout_sec=value,
        )  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [(), "debugging", ("",), (True,)])
def test_invalid_category_declaration_is_rejected(value: object) -> None:
    with pytest.raises(ValueError, match="categories"):
        select_tasks(
            [_task(i) for i in range(6)],
            dev_count=2,
            holdout_count=4,
            seed="fixed",
            categories=value,
        )  # type: ignore[arg-type]


def test_optional_scope_filters_have_no_effect_when_not_declared() -> None:
    catalog = [_task(index, agent={"timeout_sec": 7200}) for index in range(8)]
    original = select_tasks(catalog, dev_count=2, holdout_count=4, seed="fixed")
    explicit = select_tasks(
        catalog,
        dev_count=2,
        holdout_count=4,
        seed="fixed",
        categories=None,
        max_agent_timeout_sec=None,
    )
    assert original.public_dict() == explicit.public_dict()
    assert original.rules["categories"] is None
    assert original.rules["max_agent_timeout_sec"] is None


def test_cli_prepare_preserves_declared_category_and_timeout_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from sayacode_bench import cli

    catalog = [
        _task(
            index, benchmark="terminal-bench-2.1", category="debugging", agent={"timeout_sec": 900}
        )
        for index in range(4)
    ] + [_task(20, benchmark="terminal-bench-2.1", category="games", agent={"timeout_sec": 900})]
    monkeypatch.setattr(cli, "fetch_source", lambda *args: object())
    monkeypatch.setattr(cli, "build_catalog", lambda *args: catalog)
    destination = tmp_path / "selection.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "prepare",
            "--benchmark",
            "terminal-bench-2.1",
            "--cache",
            str(tmp_path / "cache"),
            "--dev",
            "1",
            "--holdout",
            "2",
            "--seed",
            "fixed",
            "--category",
            "debugging",
            "--category",
            "software-engineering",
            "--max-agent-timeout-sec",
            "1800",
            "--output",
            str(destination),
        ],
    )
    assert cli.main() == 0
    manifest = json.loads(destination.read_text(encoding="utf-8"))
    assert manifest["rules"]["categories"] == ["debugging", "software-engineering"]
    assert manifest["rules"]["max_agent_timeout_sec"] == 1800
    assert manifest["exclusions"][0]["reason"] == "outside_predeclared_category_scope"
    assert all(row["agent"]["timeout_sec"] == 900 for row in manifest["dev"] + manifest["holdout"])
