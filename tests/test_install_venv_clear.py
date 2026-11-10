"""回归：uv venv 必须带 --clear，否则已有 venv 时整条安装链失败。

背景（2026-11-10 第 3 批实测）：
sayacode 在 protonmail-webclients-09fcf0db 上 3 次安装 attempt 全失败，
trial.log 里是：

    hint: Use the `--clear` flag or set `UV_VENV_CLEAR=1` to replace
          the existing virtual environment
    install attempt 3 failed, retrying

`/installed-agent/sayacode/venv` 已存在时，`uv venv` 不加 --clear 会直接退出。
这在容器复用（Harbor 重试）或镜像预置该路径时触发，表现为
infrastructure_error / NonZeroAgentExitCodeError，被记成 reward=0。

修法：`uv venv --clear`，让安装幂等。
"""

from __future__ import annotations

import pathlib
import re

ADAPTER = pathlib.Path(r"C:\develop\sayacode-bench\src\sayacode_bench\adapter.py")


def _install_block() -> str:
    text = ADAPTER.read_text(encoding="utf-8")
    m = re.search(r"install_steps = \((.*?)\n        \)", text, re.S)
    assert m, "找不到 install_steps 定义"
    return m.group(1)


def test_uv_venv_has_clear_flag() -> None:
    """uv venv 必须带 --clear，否则已有 venv 时失败。"""
    block = _install_block()
    m = re.search(r"uv venv ([^\"]*)", block)
    assert m, "找不到 uv venv 调用"
    flags = m.group(1)
    assert "--clear" in flags, f"uv venv 缺少 --clear：{flags!r}"


def test_clear_precedes_python_flag() -> None:
    """--clear 应在 --python 之前（顺序不影响语义，但保持可读）。"""
    block = _install_block()
    m = re.search(r"uv venv ([^\"]*)", block)
    assert m
    flags = m.group(1)
    if "--clear" in flags and "--python" in flags:
        assert flags.index("--clear") < flags.index("--python")
