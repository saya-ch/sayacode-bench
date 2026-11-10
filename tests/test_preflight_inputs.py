"""回归：缺失运行输入必须在启动前报错，不能跑到一半才炸。

背景（2026-11-10 实测）：
sayacode 实验连续失败，每次都只得到 `infrastructure_error` + 类型名
`ExceptionGroup`，10 秒就返回，完全看不出原因。

逐步挖下去发现两层缺陷：
  1. `FormalPaths.require_inputs` 写好了却**从未被调用**
  2. `execution.py` 捕获异常时只记 `type(exc).__name__`，丢了 message

    ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
      └─ FileNotFoundError: 系统找不到指定的路径
         'C:\\sb\\r\\formal-study-v1\\prepared-original\\mapped-bundle\\inputs\\baseline.json'

修法：
  * run_formal_240 在启动前对每个 agent 调 require_inputs
  * execution.py 记录 harbor_exception_message（含 ExceptionGroup 子异常）
"""

from __future__ import annotations

import pathlib
import re

BENCH = pathlib.Path(r"C:\develop\sayacode-bench")
RUNNER = BENCH / "scripts" / "run_formal_240.py"
EXECUTION = BENCH / "src" / "sayacode_bench" / "execution.py"
AGENTS = BENCH / "scripts" / "locked_agents.py"


def test_require_inputs_is_called() -> None:
    """run_formal_240 必须实际调用 require_inputs（原来只有定义）。"""
    src = RUNNER.read_text(encoding="utf-8")
    assert "require_inputs(agent=" in src, "run_formal_240 没有调用 require_inputs"
    # 调用点要在跑 agent 之前
    call_at = src.index("require_inputs(agent=")
    run_at = src.index("rows = await run_agent(")
    assert call_at < run_at, "require_inputs 的调用晚于实际运行"


def test_require_inputs_covers_sayacode_inputs() -> None:
    """sayacode 的必要输入必须包含 profile/wheel/requirements/variant。"""
    src = AGENTS.read_text(encoding="utf-8")
    m = re.search(r"def require_inputs.*?(?=\n    \n|\n    @|\n\nclass )", src, re.S)
    assert m, "找不到 require_inputs 实现"
    body = m.group(0)
    for field in ("profile", "wheel", "requirements", "variant"):
        assert f"self.{field}" in body, f"require_inputs 没检查 {field}"


def test_execution_writes_exception_detail_file() -> None:
    """异常详情必须落单独文件，不能进 normalized.json。

    tests/test_execution.py 里有一条安全约束：异常 body 可能含凭据/用户数据，
    不得写进汇总记录（用 "SECRET" 断言）。所以详情只能落旁路文件。
    """
    src = EXECUTION.read_text(encoding="utf-8")
    assert "exception-detail.txt" in src, "没有把异常详情落盘"
    assert "_exception_detail" in src, "缺少异常详情展开函数"
    # 不能又把 message 塞回 record
    assert '"harbor_exception_message"' not in src, "message 进 record 会违反安全约束"


def test_exception_detail_unwraps_group() -> None:
    """_exception_detail 要把 ExceptionGroup 的子异常展开。"""

    def detail(exc, depth=0):
        if depth > 8:
            return "…"
        text = f"{type(exc).__name__}: {exc}"
        children = getattr(exc, "exceptions", None)
        if children:
            parts = [detail(c, depth + 1) for c in list(children)[:8]]
            text += "\n  └─ " + "\n  └─ ".join(parts)
        return text

    inner = FileNotFoundError("系统找不到指定的路径: 'x.json'")
    try:
        raise ExceptionGroup("unhandled errors in a TaskGroup", [inner])
    except BaseException as exc:
        out = detail(exc)
    assert "ExceptionGroup" in out
    assert "FileNotFoundError" in out
    assert "x.json" in out, f"子异常内容没展开: {out}"
