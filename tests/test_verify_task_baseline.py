"""``verify_task_baseline`` 的新题库准入判定（fake / usable / broken 三档）。

存在理由：这是新题库准入的唯一硬门槛——判错的后果是**空题进评测**（fake 被当 usable）
或**好题被丢弃**（usable 被当 fake）。此前零测试，判定逻辑内联在 ``main()`` 里。
现在抽成 ``classify_baseline`` / ``apply_baseline_filter`` 两个纯函数后在此锁定。

fixture 使用 SWE-EVO 命名（``sweevo-*``），不出现 ``instance_``。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import verify_task_baseline as module

TASK_NAME = "sweevo-dask-2022-10-0"


def test_fake_when_all_f2p_already_pass_at_baseline() -> None:
    """F2P 在基线上全过 → 题目本身已修好，不能用来区分模型。"""
    result = module.classify_baseline(
        ["tests/test_a.py::test_new"],
        ["tests/test_a.py::test_old"],
        {"tests/test_a.py::test_new": "PASSED", "tests/test_a.py::test_old": "PASSED"},
    )
    assert result["verdict"] == "fake"
    assert result["reason"] == "f2p_all_pass_at_baseline"


def test_usable_and_p2p_filtered_by_baseline_status() -> None:
    result = module.classify_baseline(
        ["tests/test_a.py::test_new"],
        ["tests/test_a.py::test_old", "tests/test_b.py::test_flaky"],
        {
            "tests/test_a.py::test_new": "FAILED",
            "tests/test_a.py::test_old": "PASSED",
            "tests/test_b.py::test_flaky": "FAILED",
        },
    )
    assert result["verdict"] == "usable"
    assert result["reason"] == "f2p_fails_at_baseline"
    # 基线就失败的 P2P 必须剔除，否则合格 agent 落地后会被误判为回归
    assert result["keep_p2p"] == ["tests/test_a.py::test_old"]


def test_unknown_when_f2p_is_empty() -> None:
    result = module.classify_baseline([], ["tests/test_a.py::test_old"], {})
    assert result["verdict"] == "unknown"
    assert result["reason"] == "no_f2p"


def test_sat_supports_parameterized_prefix_matching() -> None:
    """pytest 参数化用例在 config 里写作 ``test_x[a-b]``，日志里是 ``test_x[a]``。"""
    assert module.sat("tests/test_a.py::test_x", {"tests/test_a.py::test_x[1]": "PASSED"}) is True
    assert module.sat("tests/test_a.py::test_x", {"tests/test_b.py::test_x": "PASSED"}) is False
    assert module.sat("tests/test_a.py::test_x", {"tests/test_a.py::test_x": "FAILED"}) is False


def test_apply_baseline_filter_rewrites_config(tmp_path: Path) -> None:
    task = tmp_path / TASK_NAME
    (task / "tests").mkdir(parents=True)
    config = task / "tests" / "config.json"
    config.write_text(
        json.dumps(
            {
                "fail_to_pass": ["tests/test_a.py::test_new"],
                "pass_to_pass": ["tests/test_a.py::test_old", "tests/test_b.py::test_flaky"],
            }
        ),
        encoding="utf-8",
    )

    dropped = module.apply_baseline_filter(task, ["tests/test_a.py::test_old"])

    assert dropped == 1
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["pass_to_pass"] == ["tests/test_a.py::test_old"]
    assert written["baseline_filtered_p2p"] == 1
    # F2P 不受基线过滤影响（否则题目会失去判别力）
    assert written["fail_to_pass"] == ["tests/test_a.py::test_new"]
