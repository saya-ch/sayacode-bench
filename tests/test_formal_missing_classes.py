"""``formal.MISSING_CLASSES`` 与 ``unattributed`` 分母语义（此前无任何测试）。

存在理由（M4 审计 §3.4）：``MISSING_CLASSES`` 有 7 类，但全仓没有一条测试断言
这个集合，也没有测试验证「unattributed 不进分母、只报告」。改动这类行为不会变红，
属于静默漂移风险。

fixture 使用 SWE-EVO 命名（``sweevo-*``），不出现 ``instance_``。
"""

from __future__ import annotations

import re
from pathlib import Path

from sayacode_bench.formal import (
    MISSING_CLASSES,
    TaskSpec,
    Trial,
    build_plan,
    summarize_agent,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "PROTOCOL-V2.md"


def _protocol_missing_classes() -> set[str]:
    """从 PROTOCOL-V2 §3 的表格里解析缺失类名。

    只解析「## 3. 缺失分类」到「## 4.」之间的表格首列（形如 ``| ``infra`` |``），
    对表格列宽、说明文字、排版调整不敏感；类名本身变了才会红。
    """
    text = PROTOCOL.read_text(encoding="utf-8")
    start = text.index("## 3. 缺失分类")
    end = text.index("## 4.")
    return set(re.findall(r"^\| `([a-z_]+)` \|", text[start:end], re.M))


def test_missing_classes_exact_set() -> None:
    assert set(MISSING_CLASSES) == {
        "no_job",
        "infra",
        "timeout",
        "model_fault",
        "empty_patch",
        "unverified",
        "unattributed",
    }
    assert len(MISSING_CLASSES) == 7


def test_missing_classes_are_unique() -> None:
    assert len(set(MISSING_CLASSES)) == len(MISSING_CLASSES)


def test_every_declared_class_but_unattributed_is_reachable() -> None:
    """7 类里 6 类必须能被 ``classify_missing`` 真正返回。

    回归背景：R3 S8 的 timeout 就是这样"声明了却永远不可达"；本测试防止同类问题
    （新增类但忘记加分支）再次发生。``unattributed`` 是矩阵兜底，不由该函数返回。
    """
    from sayacode_bench.formal import classify_missing

    reachable = {
        classify_missing(None),
        classify_missing(_trial(exception_type="NonZeroAgentExitCodeError", reward=None, patch_bytes=0)),
        classify_missing(_trial(exception_type="AgentTimeoutError", reward=None, patch_bytes=None)),
        classify_missing(_trial(reward=None, faults=("ECONNRESET",))),
        classify_missing(_trial(reward=None, patch_bytes=0)),
        classify_missing(_trial(reward=None, patch_bytes=10)),
    }
    assert reachable == set(MISSING_CLASSES) - {"unattributed"}


def test_protocol_v2_lists_exactly_the_same_classes() -> None:
    """代码与协议 §3 必须逐类一致（7 类：6 个可判定 + unattributed 兜底）。"""
    documented = _protocol_missing_classes()
    assert documented == set(MISSING_CLASSES), (
        f"协议独有 {documented - set(MISSING_CLASSES)}；"
        f"代码独有 {set(MISSING_CLASSES) - documented}"
    )


def _trial(**overrides: object) -> Trial:
    base: dict[str, object] = {
        "agent": "sayacode",
        "job": "job-1",
        "kind": "native",
        "task_id": "sweevo-dask-2022-10-0",
        "repository": "dask",
        "repeat": 1,
        "reward": 1.0,
        "terminal": None,
        "patch_bytes": 120,
        "partial": None,
        "restored_tests": False,
        "stripped_tests": False,
    }
    base.update(overrides)
    return Trial(**base)  # type: ignore[arg-type]


def test_unattributed_trials_do_not_enter_planned_or_observed_denominators() -> None:
    tasks = [TaskSpec(task_id="sweevo-dask-2022-10-0", repository="dask")]
    plan = build_plan(tasks, 2)
    observed = _trial()
    stray = _trial(task_id=None, repeat=0, reward=0.0)

    result = summarize_agent("sayacode", [observed, stray], plan)

    assert result["planned"] == 2
    assert result["observed"] == 1
    # 缺失只来自计划矩阵里没被观测到的那一项，stray 不能额外制造缺失
    assert result["missing"] == 1
    assert result["missing_counts"] == {"no_job": 1}
    assert len(result["unattributed"]) == 1
    assert result["unattributed"][0]["task_id"] is None
    # 分母不受影响：1/2 而不是 1/3
    assert result["rates"]["planned_pass_rate"] == 0.5
    assert result["rates"]["observed_pass_rate"] == 1.0


def test_unattributed_rows_are_reported_with_class_marker() -> None:
    tasks = [TaskSpec(task_id="sweevo-dask-2022-10-0", repository="dask")]
    plan = build_plan(tasks, 1)
    stray = _trial(task_id=None, repeat=0)

    result = summarize_agent("sayacode", [stray], plan)

    rows = [row for row in result["trials"] if row.get("missing_class") == "unattributed"]
    assert len(rows) == 1
    assert rows[0]["job"] == "job-1"
    # unattributed 不计入 missing_counts（它不进缺失分母）
    assert "unattributed" not in result["missing_counts"]


def test_repeat_below_one_is_also_unattributed() -> None:
    tasks = [TaskSpec(task_id="sweevo-dask-2022-10-0", repository="dask")]
    plan = build_plan(tasks, 1)
    bad_repeat = _trial(repeat=0)

    result = summarize_agent("sayacode", [bad_repeat], plan)

    assert result["observed"] == 0
    assert len(result["unattributed"]) == 1
    assert result["missing_counts"] == {"no_job": 1}
