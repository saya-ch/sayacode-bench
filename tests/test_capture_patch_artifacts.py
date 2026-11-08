"""回归：补丁采集必须剔除构建产物。

真实事故（2026-11-08）：v2 实验的 flipt-io r2 产出 **24.2MB 补丁**，其中
**25,396,314 字符是 Go 编译产物 `flipt` 可执行文件**，真实代码改动只有 4,344 字符。

根因：`capture_patch` 用 `git add --intent-to-add --all` 把未跟踪文件一起收进
补丁，编译产物（ELF 二进制、含 NUL 字节、几 MB）就被带上了。

后果：
  - 补丁体积从几 KB 涨到 24MB（4000 倍）
  - 验证器应用补丁可能失败，或耗时激增
  - 存储和传输浪费

本文件锁住剔除行为，同时确保**不误伤正常源码改动**。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sayacode_bench.worker import (
    MAX_NEW_BINARY_BYTES,
    _artifact_reason,
    _looks_binary,
    capture_patch,
)

# --- 单元：单文件判定 --------------------------------------------------------


def test_small_binary_is_kept(tmp_path: Path) -> None:
    """小二进制必须保留。

    模型合法新增的测试 fixture / 图片可能只有几百字节，
    官方验证器重放补丁时需要它。这是 tests/test_adapter.py 里
    `test_patch_includes_new_binary_and_committed_changes...` 锁住的既有行为，
    不能用「是二进制就剔除」把它破坏掉。
    """
    p = tmp_path / "fixture.bin"
    p.write_bytes(bytes(range(256)))
    assert _looks_binary(p)
    assert _artifact_reason(p, "fixture.bin") is None


def test_oversized_binary_is_an_artifact(tmp_path: Path) -> None:
    """编译产物（ELF/Mach-O/class）必然是二进制且以 MB 计。"""
    p = tmp_path / "flipt"
    p.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\0" * (MAX_NEW_BINARY_BYTES + 1))
    reason = _artifact_reason(p, "flipt")
    assert reason is not None and "oversized binary" in reason


def test_large_text_is_kept(tmp_path: Path) -> None:
    """超大的文本文件不剔——可能是合法的生成数据或大型 fixture。"""
    p = tmp_path / "data.json"
    p.write_text("x" * (MAX_NEW_BINARY_BYTES + 100), encoding="utf-8")
    assert _artifact_reason(p, "data.json") is None


def test_plain_source_is_not_an_artifact(tmp_path: Path) -> None:
    """正常源码不能被误判——这是本改动最大的风险。"""
    p = tmp_path / "main.go"
    p.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    assert not _looks_binary(p)
    assert _artifact_reason(p, "main.go") is None


def test_source_with_utf8_is_not_binary(tmp_path: Path) -> None:
    """UTF-8 中文注释不能被当成二进制（没有 NUL 字节）。"""
    p = tmp_path / "comment.py"
    p.write_text("# 中文注释\nVALUE = 1\n", encoding="utf-8")
    assert _artifact_reason(p, "comment.py") is None


def test_build_directory_is_an_artifact(tmp_path: Path) -> None:
    d = tmp_path / "node_modules" / "pkg"
    d.mkdir(parents=True)
    p = d / "index.js"
    p.write_text("module.exports = 1\n", encoding="utf-8")
    assert _artifact_reason(p, "node_modules/pkg/index.js") == "build directory"


def test_artifact_suffix_is_detected(tmp_path: Path) -> None:
    p = tmp_path / "main.o"
    p.write_bytes(b"obj")
    assert _artifact_reason(p, "main.o") == "build artifact suffix"


def test_bin_directory_is_not_treated_as_build(tmp_path: Path) -> None:
    """`bin/` 不列入构建目录——有些项目把可执行脚本源码放这里，误伤代价高。"""
    d = tmp_path / "bin"
    d.mkdir()
    p = d / "tool.js"
    p.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    assert _artifact_reason(p, "bin/tool.js") is None


# --- 集成：真实 git 仓库里的 capture_patch ----------------------------------


def _run(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)} 失败: {r.stderr}")
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _run("init", "-q", cwd=root)
    _run("config", "user.email", "t@example.com", cwd=root)
    _run("config", "user.name", "t", cwd=root)
    _run("config", "commit.gpgsign", "false", cwd=root)
    (root / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    (root / "util.go").write_text("package main\n\nfunc helper() {}\n", encoding="utf-8")
    (root / "go.mod").write_text("module example.com/x\n\ngo 1.21\n", encoding="utf-8")
    _run("add", "-A", cwd=root)
    _run("commit", "-qm", "init", cwd=root)
    return root, _run("rev-parse", "HEAD", cwd=root).strip()


def _baseline(tmp_path: Path, repo: Path, commit: str) -> Path:
    path = tmp_path / "git-base.json"
    path.write_text(
        json.dumps({"available": True, "repo": str(repo), "base_commit": commit}),
        encoding="utf-8",
    )
    return path


def test_capture_patch_excludes_compiled_binary(tmp_path: Path, repo: tuple[Path, str]) -> None:
    """核心回归：改源码 + 编译出二进制，补丁里只能有源码。"""
    root, commit = repo
    # 真实的代码改动
    (root / "main.go").write_text(
        "package main\n\nfunc main() { doWork() }\n\nfunc doWork() {}\n", encoding="utf-8"
    )
    # 模拟 go build 产物：几 MB 的 ELF 风格二进制
    (root / "flipt").write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\0" * 2_000_000)

    patch = tmp_path / "model.patch"
    capture_patch(_baseline(tmp_path, root, commit), patch)

    text = patch.read_text(encoding="utf-8", errors="replace")
    assert "main.go" in text, "源码改动必须保留"
    assert "GIT binary patch" not in text, "二进制不应该出现在补丁里"
    assert len(text) < 100_000, f"补丁仍有 {len(text)} 字符，疑似没剔除干净"

    # 剔除记录要落盘，便于事后核对
    record = patch.with_name("stripped-build-artifacts.json")
    assert record.is_file()
    data = json.loads(record.read_text(encoding="utf-8"))
    assert any(item["path"] == "flipt" for item in data["stripped"])


def test_capture_patch_keeps_ordinary_new_source_file(
    tmp_path: Path, repo: tuple[Path, str]
) -> None:
    """新增的普通源码文件必须保留——不能为了剔除产物把正常改动也删了。"""
    root, commit = repo
    (root / "feature.go").write_text(
        "package main\n\nfunc feature() int { return 1 }\n", encoding="utf-8"
    )

    patch = tmp_path / "model.patch"
    capture_patch(_baseline(tmp_path, root, commit), patch)

    text = patch.read_text(encoding="utf-8", errors="replace")
    assert "feature.go" in text
    assert "func feature()" in text


def test_capture_patch_drops_node_modules(tmp_path: Path, repo: tuple[Path, str]) -> None:
    """依赖目录不进补丁。"""
    root, commit = repo
    pkg = root / "node_modules" / "leftpad"
    pkg.mkdir(parents=True)
    (pkg / "index.js").write_text("module.exports = 1\n", encoding="utf-8")
    (root / "main.go").write_text("package main\n\n// tweak\n", encoding="utf-8")

    patch = tmp_path / "model.patch"
    capture_patch(_baseline(tmp_path, root, commit), patch)

    text = patch.read_text(encoding="utf-8", errors="replace")
    assert "node_modules" not in text
    assert "main.go" in text


def test_capture_patch_still_strips_new_tests(tmp_path: Path, repo: tuple[Path, str]) -> None:
    """原有行为不能被破坏：新增测试文件仍要剔除。

    注意 Go 的测试命名是 `xxx_test.go`（不是 `test_xxx.go`），
    用错命名会让 `_looks_like_test_path` 不匹配，测试就失去意义。
    """
    root, commit = repo
    (root / "feature_test.go").write_text("package main\n", encoding="utf-8")
    (root / "main.go").write_text("package main\n\n// changed\n", encoding="utf-8")

    patch = tmp_path / "model.patch"
    capture_patch(_baseline(tmp_path, root, commit), patch)

    text = patch.read_text(encoding="utf-8", errors="replace")
    assert "feature_test.go" not in text
    assert "main.go" in text
