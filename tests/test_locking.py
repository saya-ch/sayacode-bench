"""开发选择签收的完整性与最终验收隔离。"""

import json
from copy import deepcopy

import pytest

from sayacode_bench.artifacts import file_sha256, write_json
from sayacode_bench.locking import lock_candidate, validate_candidate_receipt


@pytest.fixture
def experiment(tmp_path):
    variants = {}
    for label in ("reference", "revised"):
        path = tmp_path / f"{label}.json"
        write_json(path, {"id": label, "team_enabled": True})
        variants[label] = path
    plan = {
        "phase": "dev",
        "frozen": True,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "configurations": ["reference", "revised"],
        "baseline": "reference",
        "candidate": None,
        "repeats": 2,
        "tasks": [
            {"task_id": "dev-a", "repository": "repo", "leakage_group": "repo:fix-a"},
            {"task_id": "dev-b", "repository": "repo", "leakage_group": "repo:fix-b"},
        ],
        "artifacts": {
            "product_wheel": "a" * 64,
            "requirements": "b" * 64,
            "variants": {label: file_sha256(path) for label, path in variants.items()},
        },
    }
    rows = [
        {
            "task_id": task["task_id"],
            "configuration": label,
            "repeat": repeat,
            "status": "completed",
            "success": label == "revised",
            "verified": True,
            "canonical_model": plan["canonical_model"],
            "endpoint": "local",
            "record_complete": True,
            "input_tokens": 100,
            "output_tokens": 10,
            "usage_complete": True,
        }
        for task in plan["tasks"]
        for label in plan["configurations"]
        for repeat in (1, 2)
    ]
    manifest_path = tmp_path / "dev.json"
    records_path = tmp_path / "results" / "records.jsonl"
    write_json(manifest_path, plan)
    records_path.parent.mkdir()
    records_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return {
        "manifest": plan,
        "manifest_path": manifest_path,
        "records": rows,
        "records_path": records_path,
        "variants": variants,
        "receipt_path": tmp_path / "candidate-lock.json",
    }


def lock(experiment):
    return lock_candidate(
        experiment["manifest_path"],
        experiment["records_path"],
        experiment["variants"],
        experiment["receipt_path"],
    )


def final_manifest(experiment, *, baseline_only=False):
    plan = deepcopy(experiment["manifest"])
    plan.update(
        phase="validation" if baseline_only else "holdout",
        candidate=None if baseline_only else "revised",
        configurations=["reference"] if baseline_only else ["reference", "revised"],
        tasks=[{"task_id": "final-c", "repository": "repo", "leakage_group": "repo:fix-c"}],
    )
    if baseline_only:
        plan["artifacts"]["variants"] = {"reference": plan["artifacts"]["variants"]["reference"]}
    return plan


def save_records(experiment):
    experiment["records_path"].write_text(
        "".join(json.dumps(row) + "\n" for row in experiment["records"]), encoding="utf-8"
    )


def test_lock_contains_selection_sources_tasks_and_artifact_identity(experiment):
    receipt = lock(experiment)
    assert receipt["selected"] == "revised"
    assert receipt["dev_manifest"]["sha256"] == file_sha256(experiment["manifest_path"])
    assert receipt["dev_records"]["sha256"] == file_sha256(experiment["records_path"])
    assert receipt["dev_task_ids"] == ["dev-a", "dev-b"]
    assert receipt["dev_leakage_groups"] == ["repo:fix-a", "repo:fix-b"]
    assert receipt["artifacts"]["product_wheel"] == "a" * 64
    checked = validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))
    assert checked["receipt_sha256"] == file_sha256(experiment["receipt_path"])


def test_receipt_is_exclusive_and_never_overwrites_old_selection(experiment):
    lock(experiment)
    original = experiment["receipt_path"].read_bytes()
    with pytest.raises(FileExistsError):
        lock(experiment)
    assert experiment["receipt_path"].read_bytes() == original


@pytest.mark.parametrize("kind", ["missing", "unknown", "unfinished", "endpoint"])
def test_incomplete_or_uncomparable_development_cannot_be_locked(experiment, kind):
    if kind == "missing":
        experiment["records"].pop()
    elif kind == "unknown":
        experiment["records"][0]["success"] = None
    elif kind == "unfinished":
        experiment["records"][0]["record_complete"] = False
    else:
        experiment["records"][0]["endpoint"] = "remote"
    save_records(experiment)
    with pytest.raises(ValueError):
        lock(experiment)
    assert not experiment["receipt_path"].exists()


@pytest.mark.parametrize("marker", ["abort.json", "invalid.json"])
def test_invalid_development_batch_cannot_be_locked(experiment, marker):
    write_json(experiment["records_path"].parent / marker, {"reason": "external failure"})
    with pytest.raises(ValueError, match="中止或失效"):
        lock(experiment)


def test_unfrozen_development_is_rejected(experiment):
    experiment["manifest"]["frozen"] = False
    write_json(experiment["manifest_path"], experiment["manifest"])
    with pytest.raises(ValueError, match="已冻结"):
        lock(experiment)


def test_changed_variant_cannot_be_locked(experiment):
    write_json(experiment["variants"]["revised"], {"id": "changed"})
    with pytest.raises(ValueError, match="内容已变化"):
        lock(experiment)


@pytest.mark.parametrize("field", ["manifest_path", "records_path"])
def test_source_files_cannot_change_after_lock(experiment, field):
    lock(experiment)
    with experiment[field].open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="来源已变化"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))


@pytest.mark.parametrize("field", ["product_wheel", "requirements"])
def test_final_product_or_dependency_change_is_rejected(experiment, field):
    lock(experiment)
    plan = final_manifest(experiment)
    plan["artifacts"][field] = "c" * 64
    with pytest.raises(ValueError, match="与开发阶段不一致"):
        validate_candidate_receipt(experiment["receipt_path"], plan)


def test_final_candidate_config_change_is_rejected(experiment):
    lock(experiment)
    plan = final_manifest(experiment)
    plan["artifacts"]["variants"]["revised"] = "c" * 64
    with pytest.raises(ValueError, match="最终配置与开发不同"):
        validate_candidate_receipt(experiment["receipt_path"], plan)


def test_selected_file_is_checked_even_without_explicit_variant_paths(experiment):
    lock(experiment)
    write_json(experiment["variants"]["revised"], {"id": "changed-after-lock"})
    with pytest.raises(ValueError, match="内容已变化"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))


def test_explicit_final_variant_files_must_match_frozen_bytes(experiment, tmp_path):
    lock(experiment)
    variants = {}
    for label, original in experiment["variants"].items():
        copied = tmp_path / "copy" / original.name
        copied.parent.mkdir(exist_ok=True)
        copied.write_bytes(original.read_bytes())
        variants[label] = copied
    validate_candidate_receipt(
        experiment["receipt_path"], final_manifest(experiment), variant_paths=variants
    )
    variants["revised"].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="内容已变化"):
        validate_candidate_receipt(
            experiment["receipt_path"], final_manifest(experiment), variant_paths=variants
        )


@pytest.mark.parametrize("overlap", ["task_id", "leakage_group"])
def test_final_tasks_cannot_share_task_id_or_fix_group_with_dev(experiment, overlap):
    lock(experiment)
    plan = final_manifest(experiment)
    plan["tasks"][0][overlap] = experiment["manifest"]["tasks"][0][overlap]
    with pytest.raises(ValueError, match="泄漏"):
        validate_candidate_receipt(experiment["receipt_path"], plan)


def test_missing_fix_group_cannot_hide_overlap(experiment):
    lock(experiment)
    plan = final_manifest(experiment)
    del plan["tasks"][0]["leakage_group"]
    with pytest.raises(ValueError, match="leakage_group"):
        validate_candidate_receipt(experiment["receipt_path"], plan)


def test_duplicate_final_fix_group_cannot_be_counted_as_independent_tasks(experiment):
    lock(experiment)
    plan = final_manifest(experiment)
    plan["tasks"].append({**plan["tasks"][0], "task_id": "same-fix-another-version"})
    with pytest.raises(ValueError, match="重复修复组"):
        validate_candidate_receipt(experiment["receipt_path"], plan)


def test_receipt_variant_identity_cannot_disagree_with_frozen_artifacts(experiment):
    receipt = lock(experiment)
    receipt["variant_files"]["revised"]["sha256"] = "c" * 64
    write_json(experiment["receipt_path"], receipt)
    with pytest.raises(ValueError, match="来源身份被修改"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))


def test_tampered_selection_label_or_task_index_is_rejected(experiment):
    receipt = lock(experiment)
    receipt["selected"] = "reference"
    write_json(experiment["receipt_path"], receipt)
    with pytest.raises(ValueError, match="标签被修改"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))


def test_baseline_retention_requires_single_configuration_validation(experiment):
    for row in experiment["records"]:
        row["success"] = True
    save_records(experiment)
    receipt = lock(experiment)
    assert receipt["selected"] == "reference"
    validate_candidate_receipt(
        experiment["receipt_path"], final_manifest(experiment, baseline_only=True)
    )
    with pytest.raises(ValueError, match="不制造基线自比"):
        validate_candidate_receipt(experiment["receipt_path"], final_manifest(experiment))


def test_final_stage_cannot_switch_to_different_candidate_or_model(experiment):
    lock(experiment)
    plan = final_manifest(experiment)
    plan["canonical_model"] = "other"
    with pytest.raises(ValueError, match="最终模型"):
        validate_candidate_receipt(experiment["receipt_path"], plan)
    plan = final_manifest(experiment)
    plan["candidate"] = "unselected"
    with pytest.raises(ValueError, match="唯一候选"):
        validate_candidate_receipt(experiment["receipt_path"], plan)
