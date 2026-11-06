"""回归：噪声注入钩子（长上下文 A/B 实验的注入通道）。

背景：``docs/EXPERIMENT-CONTEXT-AB.md`` §2.4 要求基线 agent 也能接收到噪声——
SAYACODE 走 ``variant["instruction_append"]``（产品侧通道），但三个基线由 Harbor
直接传 instruction，读不到 variant。所以必须在这里加统一钩子，且**两条路产出的
instruction 必须字节一致**，否则组间不可比。

2026-11-07 实测发现该钩子此前**从未实现**（``STATUS.md:163`` 记「噪声注入钩子尚未
加入 locked_agents.py」），本文件锁住它。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import locked_agents


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试都从「未设置」开始，避免互相污染。"""
    monkeypatch.delenv(locked_agents.NOISE_ENV, raising=False)


def test_no_env_returns_instruction_unchanged() -> None:
    """未设置环境变量时必须原样返回——这是 clean 变体的路径。"""
    assert locked_agents.inject_noise("do the task") == "do the task"


def test_missing_file_returns_instruction_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """指向不存在的文件时不能崩，也不能注入半截内容。"""
    monkeypatch.setenv(locked_agents.NOISE_ENV, str(tmp_path / "nope.txt"))
    assert locked_agents.inject_noise("do the task") == "do the task"


def test_empty_file_returns_instruction_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空噪声文件等同未设置（避免注入一个只有分隔符的尾巴）。"""
    noise = tmp_path / "empty.txt"
    noise.write_text("   \n\n  ", encoding="utf-8")
    monkeypatch.setenv(locked_agents.NOISE_ENV, str(noise))
    assert locked_agents.inject_noise("do the task") == "do the task"


def test_noise_is_appended_with_separator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    noise = tmp_path / "noise.txt"
    noise.write_text("BACKGROUND MATERIAL " * 10, encoding="utf-8")
    monkeypatch.setenv(locked_agents.NOISE_ENV, str(noise))

    result = locked_agents.inject_noise("do the task")

    assert result.startswith("do the task")
    assert locked_agents.NOISE_SEPARATOR in result
    expected = "do the task" + locked_agents.NOISE_SEPARATOR + ("BACKGROUND MATERIAL " * 10)
    assert result == expected


def test_instruction_is_preserved_verbatim_before_separator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """原始 instruction 必须逐字节保留——它是 clean 与噪声两组唯一的共同部分。

    注意不能用 ``partition(SEPARATOR)``：instruction 自身就可能含 ``\\n\\n``
    （多段任务描述很常见），那样会切在错误的位置。改用「长度前缀」判定。
    """
    original = "fix the bug\n\nAcceptance: tests pass"
    noise = tmp_path / "noise.txt"
    noise.write_text("noise", encoding="utf-8")
    monkeypatch.setenv(locked_agents.NOISE_ENV, str(noise))

    result = locked_agents.inject_noise(original)

    assert result.startswith(original), "注入不得改动原始 instruction 的任何字节"
    assert result[len(original) :] == locked_agents.NOISE_SEPARATOR + "noise"


def test_injection_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一输入必须永远产出同一输出（实验可复现的前提）。"""
    noise = tmp_path / "noise.txt"
    noise.write_text("stable", encoding="utf-8")
    monkeypatch.setenv(locked_agents.NOISE_ENV, str(noise))

    first = locked_agents.inject_noise("task")
    second = locked_agents.inject_noise("task")
    assert first == second


def test_all_four_agents_call_the_hook() -> None:
    """四个 `run()` 都必须经过注入点，否则基线与 SAYACODE 的输入不一致。

    用源码静态检查（这里不是 B 类源码文本断言：它锁的是**接线关系**，
    不是某段代码的写法；函数被重命名时测试会红，这正是想要的）。
    """
    source = Path(locked_agents.__file__).read_text(encoding="utf-8")
    calls = source.count("inject_noise(instruction)")
    assert calls == 4, f"期望 4 个 run() 都调用注入钩子，实际 {calls} 处"
