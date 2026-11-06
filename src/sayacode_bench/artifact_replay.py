"""只为公开补丁工件定位来源；补丁应用和验证完全继承固定上游。"""

from __future__ import annotations

import re
from pathlib import Path

from patch_replay import PatchReplayAgent

from . import trialdir
from .artifacts import file_sha256, read_json
from .sources import SOURCES


class ArtifactReplayAgent(PatchReplayAgent):  # type: ignore[misc]
    """以真实 source.json 取代原上游对历史 result.json 的定位依赖。"""

    def _find_patch(self, task_name: str) -> Path:
        root = Path(self._source_job).resolve(strict=True)
        # 复盘 R3 S4：原先 ``glob("instance_*/source.json")`` 把 SWE-bench 的命名当前提；
        # 便携工件的 trial 目录也可能是 ``sweevo-*`` 或任意 slug。按内容定位，
        # 同时兼容「source.json 直接放在根目录」的退化布局（find_trial_files 会回退）。
        sources = trialdir.find_trial_files(root, "source.json")
        if len(sources) != 1:
            raise ValueError("便携工件必须且只能包含一份真实来源说明")
        source = sources[0]
        patch = source.parent / "agent" / str(self._patch_name)
        for path in (source.parent, source, patch.parent, patch):
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("补丁工件不允许链接或越过来源目录")
        metadata = read_json(source)
        if (
            metadata.get("schema_version") != 1
            or metadata.get("source_kind") != "actual_captured_model_patch"
            or metadata.get("benchmark") != "swe-bench-pro-v2"
            or metadata.get("revision") != SOURCES["swe-bench-pro-v2"].revision
            or metadata.get("task_id") != task_name
        ):
            raise ValueError("便携补丁的任务或公开源身份不匹配")
        digest = metadata.get("patch_sha256")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or file_sha256(patch) != digest
            or type(metadata.get("patch_bytes")) is not int
            or patch.stat().st_size != metadata["patch_bytes"]
        ):
            raise ValueError("便携补丁字节与真实来源说明不一致")
        return patch
