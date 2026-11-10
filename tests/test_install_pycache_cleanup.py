"""回归：安装后必须清 pycache，且清理步骤不能截断 && 链。

背景（2026-11-10 实测，40 题 x 4 agent 实验）：
sayacode 拿到 3 个 `infrastructure_error / 安装后 imports 检查失败`，
被记成 reward=0。查 `imports.stdout.txt` 末尾：

    File ".../langchain_core/utils/utils.py", line 10, in <module>
        from importlib.metadata import version
      File "<frozen importlib._bootstrap_external>", line 784, in _compile_bytecode
    ValueError: bad marshal data (invalid reference)

是 uv 下载的 Python 分发包里 pyc 损坏，报在标准库 import 上，
看现象像产品依赖坏了，实际与产品无关。

修法：安装末尾清掉 {ROOT}/python 与 {ROOT}/venv 下的 __pycache__，
让解释器重新编译。

第二个陷阱：清理用 `|| true` 收尾时**必须用括号包住**，
否则 `|| true;` 会截断外层的 `&&` 链，使 chmod 变成独立语句——
前面全失败也照样返回 0。这正是 L99-103 注释里记过的 set -e 陷阱。
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


def test_pycache_cleanup_present() -> None:
    """安装步骤必须清 pycache。"""
    block = _install_block()
    assert "__pycache__" in block, "install_steps 里没有清理 __pycache__"
    assert "rm -rf" in block


def test_cleanup_wrapped_in_parens() -> None:
    """清理步骤必须用括号包住，否则 || true 会截断 && 链。"""
    block = _install_block()
    assert "( find " in block, "清理步骤没用括号包住"
    assert ") && " in block, "括号后没有紧跟 &&"


def test_no_bare_or_true_semicolon() -> None:
    """不能出现裸的 `|| true; `（会截断 && 链）。"""
    block = _install_block()
    assert "|| true; " not in block, "存在裸的 || true; 会截断 && 链"


def test_chmod_still_last() -> None:
    """chmod 必须在链尾，保证前面的失败会短路。"""
    block = _install_block()
    assert "chmod -R a+rX" in block
    # chmod 之后不应再有 &&
    tail = block[block.index("chmod -R a+rX"):]
    assert "&&" not in tail, "chmod 之后还有 && 步骤"
