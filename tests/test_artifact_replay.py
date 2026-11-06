"""``ArtifactReplayAgent`` 的便携工件定位回归：不依赖 ``instance_`` 命名。

回归背景（R3 S4）：``artifact_replay.py`` 原先 ``glob("instance_*/source.json")``。
便携工件来自 SWE-EVO 或任意题库时，trial 目录名不以 ``instance_`` 开头，
会被误判为「没有来源说明」而拒绝重判。

上游 ``patch_replay`` 是仓外冻结模块；本测试用最小替身注入 ``sys.modules``，
不读取、不修改真实工具链。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from sayacode_bench.artifacts import file_sha256, write_json
from sayacode_bench.sources import SOURCES

_UPSTREAM = """from pathlib import Path


class PatchReplayAgent:
    def __init__(self, *args, source_job, patch_name="model.patch", **kwargs):
        self._source_job = Path(source_job)
        self._patch_name = patch_name

    async def setup(self, environment):
        return None

    async def run(self, instruction, environment, context):
        return None

    def version(self):
        return "1.0.0"
"""


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: Any) -> Any:
    """注入替身 ``patch_replay`` 后导入被测模块；结束后清理模块缓存。"""
    upstream = tmp_path / "patch_replay.py"
    upstream.write_text(_UPSTREAM, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("patch_replay", upstream)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "patch_replay", module)
    monkeypatch.delitem(sys.modules, "sayacode_bench.artifact_replay", raising=False)
    loaded = importlib.import_module("sayacode_bench.artifact_replay")
    yield loaded
    sys.modules.pop("sayacode_bench.artifact_replay", None)


def _source_document(task_id: str, patch: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_kind": "actual_captured_model_patch",
        "benchmark": "swe-bench-pro-v2",
        "revision": SOURCES["swe-bench-pro-v2"].revision,
        "task_id": task_id,
        "patch_sha256": file_sha256(patch),
        "patch_bytes": patch.stat().st_size,
    }


def test_sweevo_named_portable_trial_is_located(plugin: Any, tmp_path: Path) -> None:
    """便携工件的 trial 目录为 ``sweevo-*`` 时也能定位（R3 S4 回归）。"""
    trial = tmp_path / "sweevo-dask-2022-9-2-2022-10-0__R2jYLdj"
    patch = trial / "agent" / "model.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"portable patch\n")
    write_json(trial / "source.json", _source_document("sweevo-dask-2022-9-2-2022-10-0", patch))

    agent = plugin.ArtifactReplayAgent(source_job=str(tmp_path))
    assert agent._find_patch("sweevo-dask-2022-9-2-2022-10-0") == patch


def test_flat_portable_layout_is_located(plugin: Any, tmp_path: Path) -> None:
    """退化布局：``source.json`` 与 ``agent/model.patch`` 直接放在根目录。"""
    patch = tmp_path / "agent" / "model.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"flat portable patch\n")
    write_json(tmp_path / "source.json", _source_document("sweevo-dvc-1-11-13", patch))

    agent = plugin.ArtifactReplayAgent(source_job=str(tmp_path))
    assert agent._find_patch("sweevo-dvc-1-11-13") == patch


def test_multiple_sources_are_still_rejected(plugin: Any, tmp_path: Path) -> None:
    """「必须且只能一份来源说明」的约束不能被定位方式的改动放宽。"""
    for name, task_id in (("sweevo-a__1", "sweevo-a"), ("sweevo-b__2", "sweevo-b")):
        trial = tmp_path / name
        patch = trial / "agent" / "model.patch"
        patch.parent.mkdir(parents=True)
        patch.write_bytes(b"x")
        write_json(trial / "source.json", _source_document(task_id, patch))

    agent = plugin.ArtifactReplayAgent(source_job=str(tmp_path))
    with pytest.raises(ValueError, match="必须且只能包含一份"):
        agent._find_patch("sweevo-a")
