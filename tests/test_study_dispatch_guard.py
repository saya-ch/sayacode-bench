"""正式 master 首次派发与资格 cohort 链的离线测试；不请求 GitHub 或模型。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_sharded_workflow import frozen as frozen
from test_sharded_workflow import manifest

from sayacode_bench import shards
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from scripts import generate_sharded_workflow as module

MASTER = "a" * 64


def history(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"total_count": len(rows), "workflow_runs": list(rows)}]


def test_first_formal_dispatch_ignores_review_and_other_master() -> None:
    module.guard_study_dispatch(
        history(
            {"id": 8, "display_title": f"study {MASTER}"},
            {"id": 7, "display_title": f"review study {MASTER}"},
            {"id": 6, "display_title": "study " + "b" * 64},
        ),
        MASTER,
        8,
    )


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", None])
def test_any_other_formal_run_same_master_blocks_reset_regardless_of_result(
    conclusion: str | None,
) -> None:
    with pytest.raises(ValueError, match="从空账本重启"):
        module.guard_study_dispatch(
            history(
                {"id": 8, "display_title": f"study {MASTER}"},
                {
                    "id": 7,
                    "display_title": f"study {MASTER}",
                    "conclusion": conclusion,
                    "run_number": 999,
                    "workflow_id": "different-generated-file",
                },
            ),
            MASTER,
            8,
        )


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        [{"total_count": 2, "workflow_runs": []}],
        [{"total_count": 1, "workflow_runs": ["invalid"]}],
        history({"id": 8, "display_title": f"review study {MASTER}"}),
        history({"id": 7, "display_title": f"study {MASTER}"}),
        history(
            {"id": 8, "display_title": f"study {MASTER}"},
            {"id": 8, "display_title": f"study {MASTER}"},
        ),
    ],
)
def test_missing_or_uncertain_native_history_fails_closed(value: Any) -> None:
    with pytest.raises(ValueError):
        module.guard_study_dispatch(value, MASTER, 8)


def test_generated_review_is_not_an_execution_and_guard_is_before_first_source(
    frozen: SimpleNamespace, tmp_path: Path
) -> None:
    seed = tmp_path / "seed.json"
    write_json(seed, manifest())
    output = tmp_path / "workflow.yml"
    module.generate(frozen.path, frozen.bundle, output, seed_manifest=seed)
    workflow = read_json(output)
    master = frozen.plan["master"]["sha256"]
    assert f"'study {master}'" in workflow["run-name"]
    assert f"'review study {master}'" in workflow["run-name"]
    review = workflow["jobs"]["review"]
    guarded = next(step for step in review["steps"] if "dispatch-guard" in step.get("run", ""))
    assert "inputs.execute_models" in guarded["if"]
    assert "inputs.confirm_formal_scope" in guarded["if"]
    assert "inputs.confirm_actions_budget" in guarded["if"]
    assert "actions/runs?per_page=100" in guarded["run"] and "--paginate --slurp" in guarded["run"]
    assert "workflows/" not in guarded["run"]
    assert guarded["env"]["MASTER_SHA"] == master
    assert workflow["jobs"]["shard_0001"]["needs"] == ["review"]
    assert "needs.review.result == 'success'" in workflow["jobs"]["shard_0001"]["if"]


@pytest.mark.parametrize("duplicate,expected", [(False, 0), (True, 2)])
def test_guard_cli_status_without_secret_or_model(
    tmp_path: Path, monkeypatch: Any, duplicate: bool, expected: int
) -> None:
    rows = [{"id": 8, "display_title": f"study {MASTER}"}]
    if duplicate:
        rows.append({"id": 7, "display_title": f"study {MASTER}"})
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history(*rows)), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator",
            "dispatch-guard",
            "--history",
            str(path),
            "--master-sha256",
            MASTER,
            "--run-id",
            "8",
        ],
    )
    assert module.main() == expected


def cloud_cohort(frozen: SimpleNamespace, cohort: dict[str, str]) -> None:
    master_path = frozen.bundle / "inputs/master.json"
    master = read_json(master_path)
    master["qualification_host_cohort"] = cohort
    write_json(master_path, master)
    digest = file_sha256(master_path)
    plan = read_json(frozen.path)
    plan["master"]["sha256"] = digest
    authorization = frozen.bundle / "inputs/authorization.json"
    value = read_json(authorization)
    value["master_manifest_sha256"] = digest
    write_json(authorization, value)
    plan["authorization"]["sha256"] = file_sha256(authorization)
    plan["schedule"] = shards._schedule(master, digest)
    plan["schedule_sha256"] = module._hash(plan["schedule"])
    write_json(frozen.path, plan)


def test_generator_binds_public_qualification_to_same_private_runner_cohort(
    frozen: SimpleNamespace,
) -> None:
    expected = frozen.runner["host_cohort"]
    cloud_cohort(frozen, expected)
    assert (
        module.inspect_plan(frozen.path, frozen.bundle)[1]["qualification_host_cohort"] == expected
    )
    cloud_cohort(frozen, {**expected, "ImageVersion": "different-private-image"})
    with pytest.raises(ValueError, match="cohort"):
        module.inspect_plan(frozen.path, frozen.bundle)
