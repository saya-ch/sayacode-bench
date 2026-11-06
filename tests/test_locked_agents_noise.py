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


# --- 超长命令落盘（绕开 Windows 命令行 32KB 上限） ------------------------------


class _FakeEnv:
    """只实现 upload_file 的最小 environment 替身。"""

    def __init__(self) -> None:
        self.uploaded: list[tuple[Path, str]] = []

    async def upload_file(self, source_path, target_path: str) -> None:
        self.uploaded.append((Path(source_path), target_path))


def test_short_command_is_left_alone(tmp_path: Path) -> None:
    """短命令不能被动——否则每次调用都多一次 upload，白付代价。"""
    import asyncio

    env = _FakeEnv()
    result = asyncio.run(locked_agents.rewrite_if_too_long(env, "echo hi"))
    assert result == "echo hi"
    assert env.uploaded == []


def test_long_command_is_spilled_to_script() -> None:
    """超过阈值必须改成 `bash /tmp/xxx.sh`，且内容逐字节上传。"""
    import asyncio

    env = _FakeEnv()
    long_command = "mini-swe-agent --yolo --task=" + "x" * 40_000

    result = asyncio.run(locked_agents.rewrite_if_too_long(env, long_command))

    assert result.startswith("bash /tmp/bench-cmd-")
    assert result.endswith(".sh")
    assert len(env.uploaded) == 1
    _, target = env.uploaded[0]
    assert target.startswith("/tmp/bench-cmd-")


def test_spilled_content_preserves_command_verbatim() -> None:
    """落盘内容必须原样包含整条命令——任何改写都可能改变语义。"""
    import asyncio

    env = _FakeEnv()
    payload = "mini-swe-agent --yolo --task='含 引号 与 $符号 的内容'" + "y" * 30_000

    captured: list[str] = []
    original = locked_agents.spill_long_command

    async def _spy(environment, command):
        captured.append(command)
        return await original(environment, command)

    locked_agents.spill_long_command = _spy  # type: ignore[assignment]
    try:
        asyncio.run(locked_agents.rewrite_if_too_long(env, payload))
    finally:
        locked_agents.spill_long_command = original  # type: ignore[assignment]

    assert captured and captured[0] == payload


def test_threshold_matches_windows_limit() -> None:
    """阈值必须低于 Windows 的 32KB，且不能低到误伤正常命令。"""
    assert 8_000 < locked_agents.CMD_LEN_LIMIT < 32_000


def test_timeout_is_decided_before_spill() -> None:
    """timeout 判定必须在改写之前——改写后命令不再含 `mini-swe-agent --yolo`。

    这是接线顺序的回归保护：若有人把 `needs_timeout = ...` 移到
    `rewrite_if_too_long` 之后，长命令就再也套不上 timeout 了。
    """
    source = Path(locked_agents.__file__).read_text(encoding="utf-8")

    anchors = (
        'needs_timeout = "mini-swe-agent --yolo"',
        'needs_timeout = "codex exec"',
        'needs_timeout = "claude "',
        'needs_timeout = "opencode "',
    )
    for anchor in anchors:
        start = source.find(anchor)
        assert start != -1, f"找不到 {anchor}"
        rewrite_at = source.find("rewrite_if_too_long(environment, command)", start)
        assert rewrite_at > start, f"{anchor} 必须出现在 rewrite_if_too_long 之前"
