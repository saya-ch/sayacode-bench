"""汇总口径与缺失分类的单元测试；数据都是合成目录，不是模型成绩。"""

from __future__ import annotations

import json
from pathlib import Path

from sayacode_bench.formal import (
    build_plan,
    classify_missing,
    load_faults,
    load_sample,
    missing_gap_report,
    scan_agent,
    summarize,
    summarize_agent,
)

TASKS = [
    ("instance_alpha__one-aaaa", "alpha"),
    ("instance_beta__two-bbbb", "beta"),
    ("instance_gamma__three-cccc", "gamma"),
    ("instance_delta__four-dddd", "delta"),
]


def write_sample(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "size": len(TASKS),
                "tasks": [
                    {"task_id": task_id, "repo": repo} for task_id, repo in TASKS
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def make_job(
    root: Path,
    agent: str,
    task_id: str,
    repeat: int,
    *,
    reward: float | None = None,
    patch: int | None = None,
    terminal: str | None = None,
) -> Path:
    short = task_id.replace("instance_", "")[:34]
    job = root / agent / "jobs" / f"{agent}-{short}-r{repeat}"
    inner = job / f"instance_{task_id.replace('instance_', '')[:18]}__x1"
    inner.mkdir(parents=True)
    (inner / "result.json").write_text(
        json.dumps({"task_name": f"swebench-pro/{task_id}"}), encoding="utf-8"
    )
    if patch is not None:
        (inner / "agent").mkdir()
        (inner / "agent" / "model.patch").write_bytes(b"x" * patch)
    if reward is not None:
        (inner / "verifier").mkdir(exist_ok=True)
        (inner / "verifier" / "reward.txt").write_text(str(reward), encoding="utf-8")
    if terminal is not None:
        (inner / "verifier").mkdir(exist_ok=True)
        (inner / "verifier" / "terminal.json").write_text(
            json.dumps({"status": terminal, "reward": 0.0}), encoding="utf-8"
        )
    return job


def test_load_sample_requires_repo(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({"tasks": [{"task_id": "instance_a__b-1"}]}), encoding="utf-8")
    try:
        load_sample(path)
    except ValueError as exc:
        assert "repo" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺少 repo 应报错")


def test_three_denominators_and_missing_classes(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "sample.json")
    root = tmp_path / "results"
    # alpha: 两次都过
    make_job(root, "sayacode", TASKS[0][0], 1, reward=1.0, patch=100)
    make_job(root, "sayacode", TASKS[0][0], 2, reward=1.0, patch=120)
    # beta: r1 失败，r2 空 patch
    make_job(root, "sayacode", TASKS[1][0], 1, reward=0.0, patch=80)
    make_job(root, "sayacode", TASKS[1][0], 2, patch=0)
    # gamma: r1 有 patch 未验证，r2 无 job
    make_job(root, "sayacode", TASKS[2][0], 1, patch=90)
    # delta: 两次都无 job

    summary = summarize(root, sample=sample, repeats=2, agents=["sayacode"])
    data = summary["agents"]["sayacode"]
    assert data["planned"] == 8
    assert data["observed"] == 3
    assert data["passes"] == 2
    assert data["missing"] == 5
    assert data["missing_counts"] == {"empty_patch": 1, "no_job": 3, "unverified": 1}
    rates = data["rates"]
    assert rates["planned_pass_rate"] == 2 / 8
    assert rates["observed_pass_rate"] == 2 / 3
    assert rates["worst_bound"] == 2 / 8
    assert rates["best_bound"] == (2 + 5) / 8
    # 明细只包含实际存在的 job 与缺失条目，不含磁盘幽灵 job
    assert len(data["trials"]) == 8
    gap = missing_gap_report(summary)
    assert gap["total"] == 5
    assert gap["by_class"] == {"empty_patch": 1, "no_job": 3, "unverified": 1}


def test_terminal_marker_counts_as_observed_zero(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "sample.json")
    root = tmp_path / "results"
    make_job(root, "sayacode", TASKS[0][0], 1, terminal="skipped_empty_patch", patch=0)
    make_job(root, "sayacode", TASKS[0][0], 2, reward=1.0, patch=50)
    summary = summarize(root, sample=sample, repeats=2, agents=["sayacode"])
    data = summary["agents"]["sayacode"]
    assert data["observed"] == 2
    assert data["passes"] == 1
    assert data["missing"] == 6  # 其余 3 题共 6 个计划项
    terminal_row = next(row for row in data["trials"] if row.get("terminal"))
    assert terminal_row["effective_reward"] == 0.0


def test_model_fault_is_classified_before_empty_patch(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "sample.json")
    root = tmp_path / "results"
    make_job(root, "sayacode", TASKS[0][0], 1, patch=0)
    make_job(root, "sayacode", TASKS[0][0], 2, reward=1.0, patch=40)
    faults_path = root / "MODEL-FAULTS.json"
    faults_path.write_text(
        json.dumps(
            {
                "faulty": [
                    {
                        "agent": "sayacode",
                        "kind": "jobs",
                        "job": f"sayacode-{TASKS[0][0].replace('instance_', '')[:34]}-r1",
                        "faults": ["ECONNRESET"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    faults = load_faults(faults_path)
    tasks, _ = load_sample(sample)
    trials = scan_agent(root / "sayacode", "sayacode", tasks, faults)
    data = summarize_agent("sayacode", trials, build_plan(tasks, 2), faults=faults)
    assert data["missing_counts"]["model_fault"] == 1


def test_classify_missing_directly() -> None:
    from sayacode_bench.formal import Trial

    base = dict(
        agent="a", job="j", kind="native", task_id="instance_x", repository="r", repeat=1,
        reward=None, terminal=None, patch_bytes=None, partial=None,
        restored_tests=False, stripped_tests=False,
    )
    assert classify_missing(None) == "no_job"
    assert classify_missing(Trial(**base)) == "empty_patch"
    assert classify_missing(Trial(**{**base, "patch_bytes": 0})) == "empty_patch"
    assert classify_missing(Trial(**{**base, "patch_bytes": 10})) == "unverified"
    assert classify_missing(Trial(**{**base, "reward": 0.0, "patch_bytes": 10})) is None
    assert classify_missing(Trial(**{**base, "terminal": "skipped_empty_patch"})) is None


def test_restored_and_stripped_are_separate_flags(tmp_path: Path) -> None:
    sample = write_sample(tmp_path / "sample.json")
    root = tmp_path / "results"
    job = make_job(root, "sayacode", TASKS[0][0], 2, reward=1.0, patch=10)
    inner = next(job.glob("instance_*"))
    (inner / "agent" / "restored-test-files.json").write_text(json.dumps(["t.py"]), encoding="utf-8")
    (inner / "agent" / "stripped-new-test-files.json").write_text("[]", encoding="utf-8")
    summary = summarize(root, sample=sample, repeats=2, agents=["sayacode"])
    row = next(
        item for item in summary["agents"]["sayacode"]["trials"]
        if item.get("task_id") == TASKS[0][0] and item.get("kind")
    )
    assert row["restored_tests"] is True
    assert row["stripped_tests"] is False
    assert "hacked" not in row
