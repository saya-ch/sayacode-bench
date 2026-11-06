"""``convert_swe_evo.py`` 的历史坑回归（六个坑每一个都真实发生过一次）。

坑清单（来自 2026-11 接入 SWE-EVO 的排障记录）：

1. ``test_patch`` 混入 CI 配置（``.github/workflows/*.yml``）→ ``git apply`` 整块失败；
2. Windows 上写出 CRLF → 容器内 bash 执行失败；
3. 生成的镜像内解析器是 Python 3.8 → 不能用 PEP 585 注解（``dict[str, str]``）；
4. ``/logs/verifier`` 不存在 → ``reward.txt`` 写不进去；
5. pytest ``-rA`` 两种输出格式：``PASSED path::test``（行首）与 ``path::test PASSED``（行尾）；
6. 非测试源码文件混进 ``test_patch``（``src/**``），会覆盖 agent 的改动。

fixture 一律使用 SWE-EVO 命名（task 目录 ``sweevo-*``），不用 ``instance_``。
"""

from __future__ import annotations

import ast
import json

from scripts import convert_swe_evo as module

ROW = {
    "instance_id": "dask__dask-10111",
    "problem_statement": "Fix the scheduler bug.\n",
    "image": "ghcr.io/swe-evo/dask__dask-10111:latest",
    "test_patch": (
        "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
        "--- a/.github/workflows/ci.yml\n"
        "+++ b/.github/workflows/ci.yml\n"
        "@@ -1 +1 @@\n"
        "-on: pull_request\n"
        "+on: push\n"
        "diff --git a/tests/test_core.py b/tests/test_core.py\n"
        "--- a/tests/test_core.py\n"
        "+++ b/tests/test_core.py\n"
        "@@ -1 +1 @@\n"
        "-def test_old(): pass\n"
        "+def test_old(): return True\n"
    ),
    "patch": "diff --git a/src/core.py b/src/core.py\n--- a/src/core.py\n+++ b/src/core.py\n",
    "FAIL_TO_PASS": ["tests/test_core.py::test_new"],
    "PASS_TO_PASS": ["tests/test_core.py::test_old"],
}


def test_filter_test_patch_drops_ci_config_and_keeps_tests() -> None:
    filtered = module.filter_test_patch(ROW["test_patch"])
    assert "tests/test_core.py" in filtered
    assert ".github/workflows/ci.yml" not in filtered


def test_filter_test_patch_drops_non_test_source_files() -> None:
    text = (
        "diff --git a/src/core.py b/src/core.py\n"
        "--- a/src/core.py\n"
        "+++ b/src/core.py\n"
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
    )
    filtered = module.filter_test_patch(text)
    assert "src/core.py" not in filtered
    assert "tests/test_x.py" in filtered


def test_filter_test_patch_handles_empty_input() -> None:
    assert module.filter_test_patch("") == ""
    assert module.filter_test_patch("  \n\n") == ""


def test_build_writes_lf_only(tmp_path) -> None:
    """坑 2：Windows 写 CRLF 会让容器内的 bash 与 git apply 失败。"""
    task = module.build(ROW, tmp_path, "/testbed")
    for name in ("tests/test.sh", "tests/run_script.sh", "tests/test_patch.patch"):
        data = (task / name).read_bytes()
        assert b"\r\n" not in data, f"{name} 必须是 LF"
    assert (task / "solution" / "solve.sh").read_bytes().count(b"\r\n") == 0


def test_build_creates_verifier_logs_dir_and_gold_patch(tmp_path) -> None:
    """坑 4：``/logs/verifier`` 必须显式 ``mkdir -p``，否则 reward 写不进去。"""
    task = module.build(ROW, tmp_path, "/testbed")
    test_sh = (task / "tests" / "test.sh").read_text(encoding="utf-8")
    # 主流程一处 + trap 回调一处：删掉任何一处都会让 reward.txt 写不进去
    assert test_sh.count("mkdir -p /logs/verifier") >= 2
    assert "/logs/verifier/reward.txt" in test_sh
    assert (task / "tests" / "parser.py").is_file()
    cfg = json.loads((task / "tests" / "config.json").read_text(encoding="utf-8"))
    assert cfg["fail_to_pass"] == ["tests/test_core.py::test_new"]
    assert cfg["pass_to_pass"] == ["tests/test_core.py::test_old"]
    # 只写入过滤后的 test_patch（CI 配置块被丢弃）
    patch = (task / "tests" / "test_patch.patch").read_text(encoding="utf-8")
    assert patch.count("diff --git") == 1
    assert "tests/test_core.py" in patch
    assert ".github" not in patch


def test_build_writes_sweevo_task_directory_name(tmp_path) -> None:
    task = module.build(ROW, tmp_path, "/testbed")
    assert task.name == "sweevo-dask__dask-10111"
    assert (task / "instruction.md").is_file()
    assert "/testbed" in (task / "tests" / "run_script.sh").read_text(encoding="utf-8")


def test_parser_is_python38_compatible() -> None:
    """坑 3：镜像内是 Python 3.8，不能用 ``dict[str, str]`` 这类运行时注解。

    用 AST 检查注解节点，而不是文本包含——PARSER 的 docstring 里正好写着
    ``dict[str, str]`` 作为反例说明，文本断言会误命中。
    """
    tree = ast.parse(module.PARSER)
    annotated: list = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotated.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            annotated.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotated.append(node.annotation)
    for annotation in annotated:
        for sub in ast.walk(annotation):
            assert not isinstance(sub, ast.Subscript), f"PEP 585 注解：{ast.unparse(sub)}"
    compile(module.PARSER, "<parser>", "exec")


def test_parser_reads_both_pytest_summary_formats(tmp_path) -> None:
    """坑 5：行首 ``PASSED path::test`` 与行尾 ``path::test PASSED`` 都要认。"""
    log = tmp_path / "test.log"
    log.write_text(
        "PASSED tests/test_a.py::test_one\n"
        "tests/test_b.py::test_two PASSED\n"
        "FAILED tests/test_c.py::test_three\n"
        "tests/test_d.py::test_four FAILED\n",
        encoding="utf-8",
    )
    namespace: dict = {"__name__": "parser_under_test"}
    exec(module.PARSER, namespace)  # 被测对象就是生成的脚本文本
    parse_statuses = namespace["parse_statuses"]

    statuses = parse_statuses(log)
    assert statuses["tests/test_a.py::test_one"] == "PASSED"
    assert statuses["tests/test_b.py::test_two"] == "PASSED"
    assert statuses["tests/test_c.py::test_three"] == "FAILED"
    assert statuses["tests/test_d.py::test_four"] == "FAILED"


def test_parser_tolerates_missing_log(tmp_path) -> None:
    namespace: dict = {"__name__": "parser_under_test"}
    exec(module.PARSER, namespace)
    assert namespace["parse_statuses"](tmp_path / "missing.log") == {}
