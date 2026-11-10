"""回归：uv 安装必须有真回退链，不能 pip3 一失败就中断。

背景（2026-11-11 实测）：
sayacode 在第 4 批连续拿到 NonZeroAgentExitCodeError，
exception.txt 里的根因是：

    File "/usr/local/lib/python3.9/dist-packages/pip/_vendor/resolvelib/resolvers.py", line 171
        crit = self.state.criteria[name]
    KeyError: 'uv'
    TypeError: 'str' object is not callable
    WARNING: You are using pip version 21.0.1

容器里是 pip 21.0.1（2021 年版），装 uv 必崩。

而原来的逻辑是：

    if pip3; then (pip3 install uv) && ln -sf ...;
    elif uv; then ...;
    elif curl; then sh install-uv.sh;
    else exit 1; fi && ...

pip3 存在但装不上时，整条 if 分支失败，**不会进 elif**，
于是「有 pip3 但没有 uv」的镜像永远装不上，也不会回退到 curl。

修法：改成 _setup_uv() 逐级尝试，任一级成功即 return 0。
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


def test_uses_setup_function() -> None:
    """必须有 _setup_uv 函数式回退，而不是 if/elif 链。"""
    block = _install_block()
    assert "_setup_uv" in block, "没有 _setup_uv 回退函数"
    assert "_setup_uv() {" in block, "没有定义 _setup_uv"


def test_three_tiers_present() -> None:
    """三级回退都要在：pip3 / 已有 uv / curl-wget。"""
    block = _install_block()
    assert "command -v pip3" in block
    assert "command -v uv" in block
    assert "command -v curl" in block or "command -v wget" in block
    assert "install-uv.sh" in block, "缺少 curl 兜底路径"


def test_each_tier_returns() -> None:
    """每一级成功后必须 return 0，否则会继续往下走。"""
    block = _install_block()
    returns = block.count("return 0")
    assert returns >= 3, f"只有 {returns} 处 return 0，三级回退应各有一处"


def test_no_elif_chain_for_uv() -> None:
    """不能再有 `elif command -v uv` 这种会在 pip3 失败时跳过的结构。"""
    block = _install_block()
    assert "elif command -v uv" not in block, "仍在用 elif 链，pip3 失败不会回退"
