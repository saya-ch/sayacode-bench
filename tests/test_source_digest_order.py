"""目录指纹使用固定 Linux 路径顺序，Windows 不得折叠大小写。"""

from __future__ import annotations

import hashlib
import time
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import pytest
from test_cloud_qualification import experiment as experiment

from sayacode_bench.artifacts import read_json
from sayacode_bench.sources import tree_digest
from scripts import qualify_cloud

FILES = {
    "B.txt": b"uppercase",
    "a/file.txt": b"directory-first",
    "a.txt": b"prefix-neighbor",
    "z/A.txt": b"nested-uppercase",
    "z/b.txt": b"nested-lowercase",
}
LINUX_ORDER = ["B.txt", "a/file.txt", "a.txt", "z/A.txt", "z/b.txt"]


def expected_digest() -> str:
    result = hashlib.sha256()
    for name in LINUX_ORDER:
        result.update(name.encode() + b"\0")
        result.update(hashlib.sha256(FILES[name]).digest())
    return result.hexdigest()


@pytest.mark.parametrize("flavor", [PureWindowsPath, PurePosixPath])
def test_digest_preserves_linux_case_and_component_order_on_both_path_flavors(flavor: Any) -> None:
    """虚拟路径只替代文件系统边界，使用真实 Windows／Posix 的排序语义。"""

    class File:
        def __init__(self, relative: str):
            self.relative = flavor(relative)
            self.name = self.relative.name

        def relative_to(self, _: Any) -> Any:
            return self.relative

        def __lt__(self, other: Any) -> bool:
            return bool(self.relative < other.relative)

        def is_symlink(self) -> bool:
            return False

        def is_file(self) -> bool:
            return True

        def read_bytes(self) -> bytes:
            return FILES[self.relative.as_posix()]

    class Root:
        def rglob(self, _: str) -> list[File]:
            return [File(name) for name in reversed(FILES)]

    assert tree_digest(Root()) == expected_digest()  # type: ignore[arg-type]
    assert [p.as_posix() for p in sorted(map(PurePosixPath, FILES))] == LINUX_ORDER
    assert [p.as_posix() for p in sorted(map(PureWindowsPath, FILES))] != LINUX_ORDER
    assert sorted(FILES) != LINUX_ORDER  # 全字符串排序会把 a.txt 放到 a/file.txt 前。


def test_actual_directory_digest_matches_fixed_linux_semantics(tmp_path: Any) -> None:
    for name, content in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    assert tree_digest(tmp_path) == expected_digest()


@pytest.mark.parametrize("returncode", [1, 2])
def test_qualifier_failure_before_sanity_preserves_original_exit_and_log(
    experiment: Any,
    monkeypatch: Any,
    returncode: int,
) -> None:
    calls = []

    def fail_before_sanity(bundle: Any, log: Any, deadline: float) -> int:
        calls.append(bundle)
        log.write_text("原生 CLI 在写入 sanity 前失败\n", encoding="utf-8")
        return returncode

    monkeypatch.setattr(qualify_cloud, "call_qualifier", fail_before_sanity)
    result = qualify_cloud.run_batch(
        experiment.bundle,
        experiment.plan,
        experiment.preparation,
        experiment.probe,
        max_controls=4,
        deadline=time.time() + 10000,
    )
    assert len(calls) == 1
    assert result["native_cli_returncode"] == returncode
    assert result["reason"] == "qualification_cli_failed_before_sanity"
    assert result["error_type"] == "NativeQualificationCLIError"
    assert result["continuation_allowed"] is False
    assert result["complete"] is False and result["new_controls"] == 0
    assert result["native_log"].endswith("control-1.log")
    assert read_json(experiment.bundle / "batches/batch-0001/batch.json") == result
