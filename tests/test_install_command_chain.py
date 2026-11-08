"""回归：安装命令链必须能在中间步骤失败时中断并重试。

真实事故（2026-11-08）：v2 验证实验 20 个 trial 里 **7 个** 以
`RuntimeError: 安装后 version 检查失败` 告终，每个只花 20 秒。

根因不是网络或磁盘，而是 shell 语义：

    if ( set -eu; A; B; C ); then ok=1; fi

POSIX 规定 `set -e` 在 if/while 的**测试上下文**中失效，所以 A 失败不会中断，
B、C 继续执行；最后一条 `chmod` 成功就返回 0，重试逻辑永不触发。
安装失败一路滑到 `verify_installed_runtime`，报成「安装后 version 检查失败」，
把真正的原因（某一步 pip install 失败）完全藏起来。

实测对照（alpine:3.20）：
    if ( set -eu; echo a; false; echo b ); then ok=1; fi
      -> 输出 a、b，ok=1        （错误被吞）
    ( echo a && false && echo b )
      -> 输出 a，退出码 1        （正确中断）

修法：步骤之间一律用 `&&` 连接，不依赖 `set -e`；并检查 exec_as_root 的返回码。
"""

from __future__ import annotations

import pathlib
import re

import pytest

ADAPTER = pathlib.Path(r"C:\develop\sayacode-bench\src\sayacode_bench\adapter.py")


@pytest.fixture(scope="module")
def source() -> str:
    return ADAPTER.read_text(encoding="utf-8")


def _install_steps_literal(source: str) -> str:
    """截取 install_steps = ( ... ) 那一整段的源码文本。"""
    start = source.find("install_steps = (")
    assert start != -1, "找不到 install_steps 定义"
    end = source.find("\n        )\n", start)
    assert end != -1, "找不到 install_steps 结束"
    return source[start:end]


def test_install_steps_use_and_and_not_semicolon(source: str) -> None:
    """关键安装步骤之间必须用 && —— 这是本 bug 的核心修复点。"""
    block = _install_steps_literal(source)
    # 三条最关键的步骤：建 venv、装依赖、装产品 wheel
    for step in ("uv venv", "requirements.txt", "product_wheel.name"):
        idx = block.find(step)
        assert idx != -1, f"找不到步骤 {step}"
    # 这些步骤所在行必须以 && 结尾（允许行尾空白）
    joined = re.sub(r'"\s*\n\s*"', "", block)  # 合并跨行的字符串拼接
    assert joined.count("&&") >= 6, f"&& 只出现 {joined.count('&&')} 次，疑似仍有步骤用 ; 分隔"


def test_retry_loop_does_not_wrap_with_set_eu(source: str) -> None:
    """重试循环里不能再出现 `if ( set -eu; ...`。

    set -e 在 if 条件里不生效，写它只会让人误以为失败会中断。
    注意排除注释行——修复说明里为了对照会引用这个反例写法。
    """
    code_lines = [
        line for line in source.splitlines()
        if "if ( set -eu;" in line and not line.lstrip().startswith("#")
    ]
    assert not code_lines, (
        "重试循环仍在用 `if ( set -eu; ... )`——set -e 在 if 条件里失效，"
        f"步骤失败不会中断。命中行：{code_lines[:2]}"
    )


def test_install_result_return_code_is_checked(source: str) -> None:
    """exec_as_root 的返回码必须检查，否则失败静默滑到 verify 阶段。"""
    assert "install_result" in source, "没有保存安装命令的返回值"
    assert re.search(r"if install_code:", source), "没有检查安装命令的返回码"
    assert "SAYACODE 安装命令失败" in source, "缺少安装失败时的明确错误信息"


def test_verify_stage_error_message_stays_specific() -> None:
    """verify 阶段的报错不应被改成笼统描述——它定位的是「装好了但跑不起来」。

    这段代码在 installation.py，不在 adapter.py。
    """
    src = pathlib.Path(
        r"C:\develop\sayacode-bench\src\sayacode_bench\installation.py"
    ).read_text(encoding="utf-8")
    assert 'raise RuntimeError(f"安装后 {name} 检查失败")' in src
