"""回归：题集的 task_id 可能带题库前缀，路径和 job 名都必须剥掉。

背景（2026-11-09 实测）：
`studies/large-sample-v1-*.json` 里的 task_id 形如
  pro-v2/instance_ansible__ansible-xxx-v6382...
  tb21/code-from-image
  swe-evo/iterative__dvc_3.12.0_3.13.0
带题库前缀，而 tasks_root 下的题目录名是不带前缀的 native_id。

原来 run_formal_240.py 直接用 tid 做两件事，都会错：
  1) job 名 f"{name}-{tid[:34]}-r{repeat}" → 出现 `/`，被当成子目录
  2) paths.tasks_root / tid → 多套一层，题目录不存在，抛 ValueError

SWE-bench 的裸 task_id（instance_xxx）不含 `/`，不受影响，
所以修复必须是「只在含 / 时剥离」，不能无条件 split。
"""

from __future__ import annotations

import pathlib
import re

SCRIPT = pathlib.Path(r"C:\develop\sayacode-bench\scripts\run_formal_240.py")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_strips_benchmark_prefix() -> None:
    """源码里必须有剥离逻辑。"""
    src = _source()
    assert 'tid.split("/", 1)[1] if "/" in tid else tid' in src, (
        "找不到「含 / 才剥离」的逻辑——直接用 tid 会让多题库样本跑不起来"
    )


def test_path_uses_stripped_tid() -> None:
    """tasks_root 拼接必须用剥离后的名字。"""
    src = _source()
    assert "paths.tasks_root / stem" in src, "路径拼接仍在用原始 tid"
    assert "paths.tasks_root / tid" not in src, "路径拼接仍用带前缀的 tid"


def test_job_name_uses_stripped_tid() -> None:
    """job 名必须用剥离后的名字，否则会拼出带 / 的目录。"""
    src = _source()
    m = re.search(r'job = f"\{name\}-\{(\w+)\.replace', src)
    assert m, "找不到 job 命名语句"
    assert m.group(1) == "stem", f"job 名用的是 {m.group(1)}，应为 stem"


def test_prefix_strip_behaviour() -> None:
    """行为验证：模拟剥离逻辑对三种 task_id 的效果。"""

    def stem_of(tid: str) -> str:
        return tid.split("/", 1)[1] if "/" in tid else tid

    cases = {
        "tb21/code-from-image": "code-from-image",
        "promax/plantuml__plantuml-c_c910f8b": "plantuml__plantuml-c_c910f8b",
        "swe-evo/iterative__dvc_3.12.0_3.13.0": "iterative__dvc_3.12.0_3.13.0",
        # 裸 task_id 不能被改动
        "instance_ansible__ansible-40ade1f84b8b-v6382": "instance_ansible__ansible-40ade1f84b8b-v6382",
        "code-from-image": "code-from-image",
    }
    for tid, want in cases.items():
        assert stem_of(tid) == want, f"{tid} -> {stem_of(tid)}，期望 {want}"


def test_job_name_has_no_slash() -> None:
    """剥离后的 job 名不能含 /（否则 out/jobs/<带斜杠> 会变成子目录）。"""

    def job_of(name: str, tid: str, repeat: int) -> str:
        stem = tid.split("/", 1)[1] if "/" in tid else tid
        return f"{name}-{stem.replace('instance_', '')[:34]}-r{repeat}"

    for tid in ("tb21/code-from-image", "instance_ansible__ansible-40ade1f84b8b-v6382"):
        job = job_of("sayacode", tid, 1)
        assert "/" not in job, f"{tid} 生成的 job 名含斜杠: {job}"
        assert "\\" not in job
