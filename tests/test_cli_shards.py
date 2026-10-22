"""分片入口的真实帮助输出、参数传递及退出语义，不访问模型。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sayacode_bench import cli


@pytest.mark.parametrize("command", [[], ["plan-shards"], ["run-shard"], ["merge-shards"]])
def test_cli_help_is_utf8_even_with_cp1252_stdout(command: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sayacode_bench.cli", *command, "--help"],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout.decode("utf-8")
    assert b"UnicodeEncodeError" not in result.stderr


@pytest.mark.parametrize("complete,expected_code", [(True, 0), (False, 1)])
def test_run_shard_uses_local_completion_for_exit_code(
    tmp_path: Path, monkeypatch: Any, capsys: Any, complete: bool, expected_code: int
) -> None:
    variant, profile = tmp_path / "variant.json", tmp_path / "private.json"
    variant.write_text("{}", encoding="utf-8")
    profile.write_text("{}", encoding="utf-8")
    observed = {}

    async def run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        observed.update(args=args, kwargs=kwargs)
        # 全 master 尚未完成，不应让已经确认完成的单片报失败。
        return {"complete": complete, "summary": {"missing_trials": 47}}

    monkeypatch.setattr(cli, "run_shard", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "run-shard",
            "--plan",
            str(tmp_path / "plan.json"),
            "--shard-id",
            "trial-0001",
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "shard"),
            "--private-home",
            str(tmp_path / "private"),
            "--wheel",
            str(tmp_path / "product.whl"),
            "--requirements",
            str(tmp_path / "requirements.txt"),
            "--variant",
            f"baseline={variant}",
            "--connection",
            f"remote={profile}",
        ],
    )
    assert cli.main() == expected_code
    assert observed["args"][1:] == ("trial-0001", None)
    assert observed["kwargs"]["variants"] == {"baseline": variant.resolve()}
    assert observed["kwargs"]["connections"] == {"remote": profile.resolve()}
    assert "run-shard" in capsys.readouterr().out
