"""paired_compare 的配对统计测试；fixture 用非 ``instance_`` 的 task 命名。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import paired_compare

T1 = "sweevo-dask-2022-9-2_2022-10-0"
T2 = "sweevo-dask-2-21-1_2-21-2"
T3 = "sweevo-dask-2-58-1_2-58-2"


def write_summary(
    path: Path, passes: dict[tuple[str, int], bool | None], agent: str = "sayacode"
) -> Path:
    trials = []
    for (task, repeat), value in passes.items():
        trials.append(
            {
                "task_id": task,
                "repeat": repeat,
                "effective_reward": None if value is None else float(value),
            }
        )
    payload = {"schema_version": 2, "agents": {agent: {"trials": trials}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_trials_skips_unknown(tmp_path: Path) -> None:
    path = write_summary(tmp_path / "s.json", {(T1, 1): True, (T1, 2): None, (T2, 1): False})

    trials = paired_compare.load_trials(path, "sayacode")

    assert trials == {(T1, 1): True, (T2, 1): False}


def test_load_trials_missing_agent_raises(tmp_path: Path) -> None:
    path = write_summary(tmp_path / "s.json", {(T1, 1): True})
    try:
        paired_compare.load_trials(path, "claude-code")
    except ValueError as exc:
        assert "claude-code" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺 agent 应报错")


def test_compare_counts_and_stats() -> None:
    old = {(T1, 1): True, (T1, 2): False, (T2, 1): True, (T2, 2): True, (T3, 1): True}
    new = {(T1, 1): False, (T1, 2): True, (T2, 1): True, (T2, 2): True, (T3, 1): True}

    result = paired_compare.compare(old, new)

    assert result["paired_trials"] == 5
    assert result["paired_tasks"] == 3
    assert result["old_pass"] == 4
    assert result["new_pass"] == 4
    assert result["delta_pp"] == 0.0
    assert result["mcnemar"]["old_only"] == 1
    assert result["mcnemar"]["new_only"] == 1
    assert result["mcnemar"]["p_value"] == 1.0
    assert result["flips"]["total"] == 2
    assert result["bootstrap"]["tasks"] == 3


def test_compare_asymmetric_delta_and_p() -> None:
    old = {(T1, 1): True, (T1, 2): True, (T2, 1): True}
    new = {(T1, 1): False, (T1, 2): False, (T2, 1): True}

    result = paired_compare.compare(old, new)

    assert result["old_pass"] == 3
    assert result["new_pass"] == 1
    assert result["delta_pp"] == pytest.approx(-200 / 3)
    assert result["mcnemar"]["old_only"] == 2
    assert result["mcnemar"]["new_only"] == 0
    # 双侧精确检验：2 * C(2,0) / 2^2 = 0.5
    assert result["mcnemar"]["p_value"] == 0.5
    assert result["flips"]["old_only"] == 2
    assert result["flips"]["new_only"] == 0


def test_compare_no_overlap_raises() -> None:
    try:
        paired_compare.compare({(T1, 1): True}, {(T2, 1): True})
    except ValueError as exc:
        assert "配对" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("无交集应报错")


def test_main_writes_json(tmp_path: Path) -> None:
    old = write_summary(tmp_path / "old.json", {(T1, 1): True, (T1, 2): True, (T2, 1): True})
    new = write_summary(tmp_path / "new.json", {(T1, 1): False, (T1, 2): True, (T2, 1): True})
    out = tmp_path / "paired.json"

    code = paired_compare.main(["--old", str(old), "--new", str(new), "--out", str(out)])

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["paired_trials"] == 3
    assert payload["agent"] == "sayacode"
    assert payload["mcnemar"]["p_value"] == 1.0
    assert payload["bootstrap"]["samples"] == paired_compare.SAMPLES
    assert payload["bootstrap"]["seed"] == paired_compare.SEED
