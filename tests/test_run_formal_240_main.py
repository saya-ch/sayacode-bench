"""``run_formal_240`` 的并发决策与续跑判据（纯逻辑，不启动 Docker）。

存在理由：这四条逻辑此前**没有任何测试**，而它们各自对应一次真实事故
（见 ``docs/review/round2/M4-test-quality.md`` §6.3 覆盖盲区）：

- 内存自适应并发：曾把 WSL 的 Docker VM 打爆；
- 验证器限流：并行 verify 争内存被 OOM kill；
- 续跑判据：阶段1（``--skip-verifier``）完成后重复进入，撞 request hash；
- ``docker stats`` 单位解析：解析错会让「自适应」静默失效。

fixture 一律使用 SWE-EVO 命名（``sweevo-*``），不依赖 ``instance_`` 前缀。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_formal_240 as module

SWEEVO_TRIAL = "sweevo-dask-2022-10-0__Ab12Cd"


def test_docker_stats_are_converted_to_megabytes() -> None:
    text = "512MiB / 8GiB\n1.5GiB / 8GiB\n2048KiB / 8GiB\n500B / 8GiB\n"
    # 精确值：MiB→MB 原值、GiB×1024、KiB/1e3、B/1e6（单位解析错会让自适应静默失效）
    assert module.parse_docker_stats_mb(text) == pytest.approx(
        512 + 1536 + 2.048 + 0.0005, abs=1e-6
    )


def test_docker_stats_ignore_unparsable_lines() -> None:
    assert module.parse_docker_stats_mb("") == 0.0
    assert module.parse_docker_stats_mb("garbage\nN/A\n") == 0.0


def test_ema_first_sample_and_smoothing() -> None:
    # 首次采样直接取原值，避免从 0 缓慢爬升导致「内存已高但并发不降」
    assert module.update_ema(0.0, 1000.0) == 1000.0
    assert module.update_ema(1000.0, 2000.0) == pytest.approx(1300.0)


@pytest.mark.parametrize(
    ("ema", "expected"),
    [(7500.0, 1), (6500.0, 2), (5500.0, 4), (4500.0, 6), (3500.0, 9), (1000.0, 12)],
)
def test_concurrency_decision_by_smoothed_memory(ema: float, expected: int) -> None:
    assert module.decide_limit(ema, 12) == expected


def test_concurrency_decision_never_exceeds_caller_limit_or_drops_below_one() -> None:
    assert module.decide_limit(1000.0, 3) == 3
    assert module.decide_limit(7500.0, 0) == 1


@pytest.mark.parametrize(
    ("ema", "expected"), [(4500.0, 2), (4600.0, 1), (2000.0, 2), (9000.0, 1)]
)
def test_verifier_limit_tightens_only_when_memory_is_high(ema: float, expected: int) -> None:
    assert module.decide_verifier_limit(ema) == expected


def test_skip_existing_recognizes_sweevo_reward(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "job-1"
    trial = job_dir / SWEEVO_TRIAL
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier" / "reward.txt").write_text("1.0", encoding="utf-8")

    assert module.should_skip_existing(job_dir, skip_existing=True) is True
    # 未开启 --skip-existing 时绝不能跳过（否则会丢结果）
    assert module.should_skip_existing(job_dir, skip_existing=False) is False


def test_skip_existing_recognizes_terminal_marker(tmp_path: Path) -> None:
    job_dir = tmp_path / "jobs" / "job-2"
    trial = job_dir / SWEEVO_TRIAL
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier" / "terminal.json").write_text(
        '{"state": "skipped_empty_patch"}', encoding="utf-8"
    )

    assert module.should_skip_existing(job_dir, skip_existing=True) is True


def test_skip_existing_honours_record_complete_for_skip_verifier(tmp_path: Path) -> None:
    """阶段1 只有 ``normalized.json``：续跑必须认它，否则重复进入撞 hash。"""
    job_dir = tmp_path / "jobs" / "job-3"
    job_dir.mkdir(parents=True)
    record = job_dir / "normalized.json"

    record.write_text('{"record_complete": true}', encoding="utf-8")
    assert module.should_skip_existing(job_dir, skip_existing=True) is True

    record.write_text('{"record_complete": false}', encoding="utf-8")
    assert module.should_skip_existing(job_dir, skip_existing=True) is False

    record.write_text("{not json", encoding="utf-8")
    assert module.should_skip_existing(job_dir, skip_existing=True) is False


def test_skip_existing_requires_actual_completion_evidence(tmp_path: Path) -> None:
    """只有空 trial 目录时不得跳过（否则真正要跑的题被静默丢弃）。"""
    job_dir = tmp_path / "jobs" / "job-4"
    (job_dir / SWEEVO_TRIAL / "agent").mkdir(parents=True)

    assert module.should_skip_existing(job_dir, skip_existing=True) is False
