"""回归：长上下文实验的「文件 + 短提示」注入通道。

历史：2026-11-07 第一次用「把噪声拼进 instruction」的方式跑，SAYACODE 12/12 成功，
但三个基线 100% 失败——三条传参通道各有各的长度限制：
  mini-swe    argv ``--task=``  → Linux ``execve`` 单参数上限（Argument list too long）
  Claude Code 环境变量          → Windows 命令行 32KB（WinError 206）
  SAYACODE    ``--instruction <file>`` → 不受限

所以四组统一改成「噪声写容器内文件 + instruction 只带固定短提示」。
本文件锁住这个通道的行为，尤其是**提示必须固定**（四组收到逐字节一致的内容）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sayacode_bench import noise


class _FakeEnv:
    """只实现 upload_file 的最小 environment 替身。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.uploaded: list[tuple[str, str]] = []
        self.fail = fail

    async def upload_file(self, source_path, target_path: str) -> None:
        if self.fail:
            raise OSError("upload boom")
        self.uploaded.append((Path(source_path).read_text(encoding="utf-8"), target_path))


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(noise.NOISE_ENV, raising=False)


def _write_noise(tmp_path: Path, content: str = "ARCHIVE " * 100) -> Path:
    p = tmp_path / "noise.txt"
    p.write_text(content, encoding="utf-8")
    return p


def test_no_env_returns_instruction(tmp_path: Path) -> None:
    """clean 组：未配置噪声时一个字都不改。"""
    env = _FakeEnv()
    result = asyncio.run(noise.stage_background("do the task", env))
    assert result == "do the task"
    assert env.uploaded == []


def test_missing_file_returns_instruction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(noise.NOISE_ENV, str(tmp_path / "nope.txt"))
    env = _FakeEnv()
    assert asyncio.run(noise.stage_background("do the task", env)) == "do the task"
    assert env.uploaded == []


def test_empty_file_returns_instruction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "empty.txt"
    p.write_text("   \n", encoding="utf-8")
    monkeypatch.setenv(noise.NOISE_ENV, str(p))
    env = _FakeEnv()
    assert asyncio.run(noise.stage_background("do the task", env)) == "do the task"


def test_uploads_to_fixed_path_and_appends_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "ARCHIVE CONTENT " * 50
    monkeypatch.setenv(noise.NOISE_ENV, str(_write_noise(tmp_path, content)))
    env = _FakeEnv()

    result = asyncio.run(noise.stage_background("fix the bug", env))

    # 上传到固定路径，内容逐字节一致
    assert len(env.uploaded) == 1
    uploaded_text, target = env.uploaded[0]
    assert uploaded_text == content
    assert target == noise.BACKGROUND_PATH

    # 原 instruction 逐字节保留在前，提示附在后面
    assert result.startswith("fix the bug")
    assert noise.BACKGROUND_HINT.format(
        path=noise.BACKGROUND_PATH, chars=len(content)
    ) in result


def test_hint_is_identical_across_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """四组收到**逐字节一致**的提示——提示里绝不能含题目相关内容。"""
    monkeypatch.setenv(noise.NOISE_ENV, str(_write_noise(tmp_path, "X" * 500)))

    a = asyncio.run(noise.stage_background("task A", _FakeEnv()))
    b = asyncio.run(noise.stage_background("task B", _FakeEnv()))

    hint_a = a[len("task A") :]
    hint_b = b[len("task B") :]
    assert hint_a == hint_b


def test_hint_states_material_is_irrelevant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """提示必须明说「与你要修的问题无关」，否则模型会把它当任务线索。"""
    monkeypatch.setenv(noise.NOISE_ENV, str(_write_noise(tmp_path, "Z" * 300)))
    result = asyncio.run(noise.stage_background("t", _FakeEnv()))
    assert "无关" in result
    assert "不要" in result  # 「不要总结或复述」


def test_hint_tells_how_to_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """必须给出读取方式与分块提示，否则可能只读到开头几行。"""
    monkeypatch.setenv(noise.NOISE_ENV, str(_write_noise(tmp_path, "Y" * 300)))
    result = asyncio.run(noise.stage_background("t", _FakeEnv()))
    assert "cat" in result
    assert "分块" in result or "截断" in result


def test_upload_failure_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上传失败不能让整个 trial 崩掉——降级为原 instruction。"""
    monkeypatch.setenv(noise.NOISE_ENV, str(_write_noise(tmp_path, "Q" * 300)))
    env = _FakeEnv(fail=True)
    result = asyncio.run(noise.stage_background("original task", env))
    assert result == "original task"


def test_all_four_baselines_use_the_file_channel() -> None:
    """四个基线的 run() 必须走文件通道，不能再用会撞长度上限的 inject_noise。"""
    from scripts import locked_agents

    source = Path(locked_agents.__file__).read_text(encoding="utf-8")
    assert source.count("await stage_background(instruction, environment)") == 4
    # 旧方式不应再被 run() 调用
    assert "super().run(inject_noise(" not in source


def test_sayacode_adapter_uses_the_same_channel() -> None:
    """SAYACODE 必须走同一个函数，否则四组输入不可比。"""
    from sayacode_bench import adapter

    source = Path(adapter.__file__).read_text(encoding="utf-8")
    assert "stage_background(instruction, environment)" in source
    assert "from .noise import stage_background" in source
