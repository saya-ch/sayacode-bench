"""机制层测试保护的行为验证：恢复既有测试文件，保留新增测试与源码改动。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\develop\sayacode-bench\src")

from sayacode_bench.worker import restore_existing_test_files, strip_new_test_files  # noqa: E402


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_PAGER": "cat", "PATH": __import__("os").environ["PATH"]},
        check=True,
    )


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_restore_existing_test_files() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "tests").mkdir()
        (repo / "src").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        (repo / "tests" / "test_b.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
        (repo / "src" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        base = commit_all(repo, "base")

        # Agent 行为：改既有测试、删既有测试、新增测试、改源码
        (repo / "tests" / "test_a.py").write_text("def test_a_rewritten():\n    assert False\n", encoding="utf-8")
        (repo / "tests" / "test_b.py").unlink()
        (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
        (repo / "src" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")

        environment = {"GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"}

        def execute(*args: str, stdout: object = subprocess.PIPE) -> subprocess.CompletedProcess[bytes]:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                env=environment, stdout=stdout, stderr=subprocess.PIPE, timeout=120, check=False,
            )
            if result.returncode:
                raise RuntimeError(f"git {args} failed")
            return result

        restored = restore_existing_test_files(execute, repo, base)
        assert sorted(restored) == ["tests/test_a.py", "tests/test_b.py"], restored
        assert "test_a_rewritten" not in (repo / "tests" / "test_a.py").read_text(encoding="utf-8")
        assert (repo / "tests" / "test_b.py").is_file()
        assert "test_new" in (repo / "tests" / "test_new.py").read_text(encoding="utf-8")
        assert "VALUE = 2" in (repo / "src" / "mod.py").read_text(encoding="utf-8")

        # 恢复后的 diff 不再包含既有测试的改动
        diff_names = execute("diff", "--name-only", "--diff-filter=MD", base, "--").stdout.decode().split()
        assert "tests/test_a.py" not in diff_names and "tests/test_b.py" not in diff_names, diff_names
        assert "src/mod.py" in diff_names, diff_names

        print("验证通过：既有测试被恢复，新增测试与源码改动保留")
        print(f"恢复清单: {json.dumps(restored)}")


def test_strip_new_test_files() -> None:
    """新增的测试文件从补丁剔除，新增源码保留。"""

    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "src").mkdir()
        (repo / "src" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        base = commit_all(repo, "base")

        # Agent 新增一个测试文件（想掩盖缺陷）和一个真正的源码文件
        (repo / "tests").mkdir()
        (repo / "tests" / "test_new.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        (repo / "src" / "feature.py").write_text("FEATURE = True\n", encoding="utf-8")

        environment = {"GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"}

        def execute(*args: str, stdout: object = subprocess.PIPE) -> subprocess.CompletedProcess[bytes]:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                env=environment, stdout=stdout, stderr=subprocess.PIPE, timeout=120, check=False,
            )
            if result.returncode:
                raise RuntimeError(f"git {args} failed")
            return result

        execute("add", "--intent-to-add", "--all")
        before = execute("diff", "--name-only", base, "--").stdout.decode().split()
        assert "tests/test_new.py" in before and "src/feature.py" in before, before

        stripped = strip_new_test_files(execute, repo, base)
        assert stripped == ["tests/test_new.py"], stripped
        after = execute("diff", "--name-only", base, "--").stdout.decode().split()
        assert "tests/test_new.py" not in after, after
        assert "src/feature.py" in after, after
        # 工作区文件仍在（只是不进补丁）
        assert (repo / "tests" / "test_new.py").is_file()
        print("验证通过：新增测试剔除，新增源码保留")


if __name__ == "__main__":
    main()
