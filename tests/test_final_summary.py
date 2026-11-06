"""final_summary 的默认参数、partial 汇总与端到端重建测试。

fixture 全部使用**非 ``instance_`` 命名**（SWE-EVO 风格），确保 trial 定位按内容而非前缀。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import final_summary

TASK = "sweevo-dask-2022-9-2_2022-10-0"
TASK2 = "sweevo-dask-2-21-1_2-21-2"


def short(task_id: str) -> str:
    prefix = "instance_"
    return task_id[len(prefix) :] if task_id.startswith(prefix) else task_id


def make_trial(
    job_dir: Path,
    task_id: str,
    *,
    tests: list[dict[str, str]] | None = None,
    patch: bytes = b"diff --git a/x b/x\n",
    trial_name: str = "sweevo-trial__R2jYLdj",
) -> Path:
    trial = job_dir / trial_name
    (trial / "agent").mkdir(parents=True, exist_ok=True)
    (trial / "result.json").write_text(
        json.dumps({"task_name": f"swebench-pro/{task_id}"}), encoding="utf-8"
    )
    (trial / "agent" / "model.patch").write_bytes(patch)
    if tests is not None:
        verifier = trial / "verifier"
        verifier.mkdir(exist_ok=True)
        (verifier / "output.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
    return trial


def job_name(agent: str, task_id: str, repeat: int) -> str:
    return f"{agent}-{short(task_id)[:34]}-r{repeat}"


def test_default_root_is_v2_and_agents_are_four() -> None:
    assert final_summary.DEFAULT_ROOT == Path(r"C:\sb\hard\v2-325")
    assert final_summary.DEFAULT_AGENTS == [
        "sayacode",
        "mini-swe",
        "claude-code",
        "opencode",
    ]


def test_parser_defaults_and_help_example(monkeypatch) -> None:
    monkeypatch.delenv("SAYACODE_BENCH_FORMAL_ROOT", raising=False)
    parser = final_summary.build_parser()
    assert parser.get_default("root") == Path(r"C:\sb\hard\v2-325")
    assert parser.get_default("agents") == [
        "sayacode",
        "mini-swe",
        "claude-code",
        "opencode",
    ]
    help_text = parser.format_help()
    assert "v4-327" in help_text
    assert "rebuild-v2" in help_text
    assert "codex" in help_text


def test_partial_summary_reads_output_json(tmp_path: Path) -> None:
    job = tmp_path / "sayacode" / "jobs" / job_name("sayacode", TASK, 1)
    make_trial(
        job,
        TASK,
        tests=[{"name": "a", "status": "PASSED"}, {"name": "b", "status": "FAILED"}],
    )
    result = final_summary.partial_summary(tmp_path, ["sayacode"])

    assert result["sayacode"]["n"] == 1
    assert result["sayacode"]["trial_mean"] == 0.5
    assert result["sayacode"]["task_n"] == 1
    assert result["sayacode"]["source"] == "verifier/output.json"


def test_partial_summary_falls_back_to_verify_dir(tmp_path: Path) -> None:
    """SAYACODE 的 output.json 只在 verify 目录产生：native 缺失时必须回退。"""
    native = tmp_path / "sayacode" / "jobs" / job_name("sayacode", TASK, 1)
    make_trial(native, TASK, tests=None)
    verify = tmp_path / "sayacode" / "verify" / "jobs" / f"verify-{native.name}"
    make_trial(verify, TASK, tests=[{"name": "a", "status": "PASSED"}])
    result = final_summary.partial_summary(tmp_path, ["sayacode"])

    assert result["sayacode"]["n"] == 1
    assert result["sayacode"]["trial_mean"] == 1.0


def test_main_end_to_end_with_non_instance_tasks(tmp_path: Path) -> None:
    sample = tmp_path / "sample.json"
    sample.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "size": 2,
                "tasks": [
                    {"task_id": TASK, "repo": "dask"},
                    {"task_id": TASK2, "repo": "dask"},
                ],
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "results"
    job = root / "sayacode" / "jobs" / job_name("sayacode", TASK, 1)
    make_trial(
        job,
        TASK,
        tests=[{"name": "a", "status": "PASSED"}, {"name": "b", "status": "FAILED"}],
    )
    out = tmp_path / "out.json"

    code = final_summary.main(
        [
            "--root",
            str(root),
            "--sample",
            str(sample),
            "--agents",
            "sayacode",
            "--out",
            str(out),
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    # 2 题 × 2 重复 = 4 个计划项；只有 1 个 trial 落地（且无 reward）
    assert payload["agents"]["sayacode"]["planned"] == 4
    assert payload["agents"]["sayacode"]["observed"] == 0
    assert payload["agents"]["sayacode"]["missing"] == 4
    assert payload["partial"]["sayacode"]["n"] == 1
    assert payload["partial"]["sayacode"]["trial_mean"] == 0.5
    assert payload["stats"]["agents"]["sayacode"]["task_macro"]["complete_tasks"] == 0
