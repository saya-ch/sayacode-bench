"""``sayacode_bench.trialdir`` 的回归测试。

存在理由：commit ``46f57f0`` 曾修掉 4 处 ``instance_`` 前缀假设，但**没有写任何
测试**，于是同类假设在其余 15 处继续存活，直到 2026-11-07 复盘才被发现
（见 ``docs/review/2026-11-07/R3-infrastructure.md`` S1/S3/S5）。

本文件用**两种真实目录命名**分别构造 job 树，确保任何一处退回前缀假设都会
立即失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sayacode_bench import trialdir

#: SWE-bench Pro V2 的 trial 目录命名
SWE_BENCH_TRIAL = "instance_ansible__ansible-415e08c2970757472314e515cb63a51ad825c45e__aB3dEf"
#: SWE-EVO 的 trial 目录命名（不含 ``instance_`` 前缀）
SWE_EVO_TRIAL = "sweevo-dask-dask-2022-9-2-2022-10-0__R2jYLdj"


def _make_trial(job: Path, name: str, *, result: bool = True, reward: float | None = None) -> Path:
    trial = job / name
    (trial / "agent").mkdir(parents=True)
    (trial / "verifier").mkdir(parents=True)
    (trial / "agent" / "model.patch").write_text("--- a/x\n+++ b/x\n", encoding="utf-8")
    if result:
        (trial / "result.json").write_text('{"task_name": "x"}', encoding="utf-8")
    if reward is not None:
        (trial / "verifier" / "reward.txt").write_text(str(reward), encoding="utf-8")
    return trial


@pytest.mark.parametrize("trial_name", [SWE_BENCH_TRIAL, SWE_EVO_TRIAL])
def test_find_trial_dir_by_content_not_prefix(tmp_path: Path, trial_name: str) -> None:
    """两种命名都必须能定位到 trial 目录 —— 这是本模块存在的全部理由。"""
    job = tmp_path / "job"
    job.mkdir()
    expected = _make_trial(job, trial_name)
    assert trialdir.find_trial_dir(job) == expected


@pytest.mark.parametrize("trial_name", [SWE_BENCH_TRIAL, SWE_EVO_TRIAL])
def test_find_trial_file_both_namings(tmp_path: Path, trial_name: str) -> None:
    job = tmp_path / "job"
    job.mkdir()
    trial = _make_trial(job, trial_name, reward=1.0)
    assert trialdir.find_trial_file(job, *trialdir.REWARD_PARTS) == trial / "verifier" / "reward.txt"
    assert trialdir.find_trial_file(job, *trialdir.PATCH_PARTS) == trial / "agent" / "model.patch"
    assert trialdir.has_trial_file(job, *trialdir.RESULT_PARTS) is True


def test_missing_product_returns_none(tmp_path: Path) -> None:
    """产物不存在时必须返回 None，而不是退化成「某个文件」或抛异常。"""
    job = tmp_path / "job"
    job.mkdir()
    _make_trial(job, SWE_EVO_TRIAL, reward=None)
    assert trialdir.find_trial_file(job, *trialdir.REWARD_PARTS) is None
    assert trialdir.has_trial_file(job, *trialdir.TERMINAL_PARTS) is False


def test_empty_job_dir_returns_none(tmp_path: Path) -> None:
    """空 job 目录不能崩，也不能返回一个不存在的路径。"""
    job = tmp_path / "job"
    job.mkdir()
    assert trialdir.find_trial_dir(job) is None
    assert trialdir.iter_trial_dirs(job) == []
    assert trialdir.find_trial_file(job, *trialdir.REWARD_PARTS) is None


def test_nonexistent_job_dir_returns_none(tmp_path: Path) -> None:
    """目录不存在时（如 Redis 式的并发清理）必须静默返回 None。"""
    missing = tmp_path / "nope"
    assert trialdir.find_trial_dir(missing) is None
    assert trialdir.iter_trial_dirs(missing) == []
    assert trialdir.find_trial_file(missing, *trialdir.RESULT_PARTS) is None


def test_job_itself_is_trial_dir(tmp_path: Path) -> None:
    """退化布局：产物直接放在 job 目录下（无 trial 子目录）。"""
    job = tmp_path / "job"
    job.mkdir()
    (job / "verifier").mkdir()
    (job / "verifier" / "reward.txt").write_text("1.0", encoding="utf-8")
    assert trialdir.find_trial_dir(job) == job
    assert trialdir.find_trial_file(job, *trialdir.REWARD_PARTS) == job / "verifier" / "reward.txt"


def test_multiple_trials_prefers_one_with_result(tmp_path: Path) -> None:
    """一个 job 下有多个 trial 目录时，优先取含 result.json 的那个。"""
    job = tmp_path / "job"
    job.mkdir()
    stale = _make_trial(job, SWE_EVO_TRIAL + "-stale", result=False)
    fresh = _make_trial(job, SWE_EVO_TRIAL + "-fresh", result=True)
    assert stale != fresh
    assert trialdir.find_trial_dir(job) == fresh


def test_iter_trial_dirs_returns_all(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    a = _make_trial(job, "aaa__1")
    b = _make_trial(job, "bbb__2")
    assert trialdir.iter_trial_dirs(job) == [a, b]


def test_find_trial_files_aggregates(tmp_path: Path) -> None:
    """需要遍历多 trial（如批量重判）时用复数版本。"""
    job = tmp_path / "job"
    job.mkdir()
    a = _make_trial(job, "aaa__1", reward=1.0)
    b = _make_trial(job, "bbb__2", reward=0.0)
    hits = trialdir.find_trial_files(job, *trialdir.REWARD_PARTS)
    assert hits == [a / "verifier" / "reward.txt", b / "verifier" / "reward.txt"]


def test_prefix_is_not_the_criterion() -> None:
    """显式断言：即使目录名以 ``instance_`` 开头也不因此被判定为 trial。

    这条防的是「有人为了省事把 is_trial_dir 改回 startswith」。
    """
    assert "instance_" not in trialdir.TRIAL_MARKERS
    assert all("instance_" not in marker for marker in trialdir.TRIAL_MARKERS)
