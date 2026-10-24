"""执行模板中的真实输入检查与安全归档恢复；不调用 GitHub 或模型。"""

from __future__ import annotations

import json
import re
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from sayacode_bench import release_evidence
from sayacode_bench.artifacts import file_sha256, write_json

TEMPLATE = Path(__file__).resolve().parents[1] / ".github/workflows/preflight-installations.yml"


def workflow() -> dict[str, Any]:
    return dict(yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))


def body(job: str, name: str) -> str:
    step = next(row for row in workflow()["jobs"][job]["steps"] if row.get("name") == name)
    match = re.search(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", step["run"], re.DOTALL)
    assert match is not None
    return match[1]


@pytest.fixture
def guarded(tmp_path: Path, monkeypatch: Any) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    write_json(
        evidence / "repository.json",
        {"id": 1429748203, "private": True, "full_name": "saya-ch/sayacode-bench-runs"},
    )
    for key, value in {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ATTEMPT": "1",
        "SOURCE_SHA": "a" * 40,
        "SEED_MANIFEST_FILE": "installation-seed.json",
        "CASE_INDICES_JSON": "[1,2]",
        "CASE_INDEX": "1",
        "CASE_GROUP_JSON": "[1,2]",
    }.items():
        monkeypatch.setenv(key, value)


def test_private_first_attempt_input_guard_executes(guarded: None) -> None:
    exec(compile(body("case", "核实私有仓库、首次尝试和输入边界"), str(TEMPLATE), "exec"), {})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("SOURCE_SHA", "main"),
        ("SEED_MANIFEST_FILE", "../private.json"),
        ("CASE_INDICES_JSON", "[1,1]"),
        ("CASE_INDICES_JSON", "[true]"),
        ("CASE_INDICES_JSON", '["1"]'),
        ("CASE_INDICES_JSON", "[0]"),
        ("CASE_INDICES_JSON", "[47]"),
        ("CASE_INDICES_JSON", "[]"),
        ("CASE_INDEX", "3"),
    ],
)
def test_invalid_dispatch_inputs_stop_before_install(
    guarded: None, monkeypatch: Any, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(AssertionError):
        exec(compile(body("case", "核实私有仓库、首次尝试和输入边界"), str(TEMPLATE), "exec"), {})


@pytest.fixture
def restored(tmp_path: Path, monkeypatch: Any) -> dict[str, Any]:
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    checkout = tmp_path / "bench"
    checkout.mkdir()
    artifacts = tmp_path / "execution/artifacts"
    artifacts.mkdir(parents=True)
    root = tmp_path / "bundle"
    originals = tmp_path / "originals"
    originals.mkdir()
    archives: dict[str, Path] = {}

    def make_archive(name: str, members: dict[str, str]) -> dict[str, str]:
        folder = originals / name
        folder.mkdir()
        for relative, text in members.items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        archive = originals / (name + ".tar.gz")
        with tarfile.open(archive, "w:gz") as stream:
            for path in folder.iterdir():
                stream.add(path, arcname=path.name)
        digest = file_sha256(archive)
        archives[digest] = archive
        return {"archive_sha256": digest}

    seed = make_archive("seed", {"inputs/original.json": '{"original":true}\n'})
    write_json(artifacts / "installation-seed.json", seed)
    handoff = temporary / "case-handoffs/installation-case-456-1"
    (handoff / "evidence").mkdir(parents=True)
    case = make_archive(
        "case",
        {"installations/restart-v2/case-0001/case-receipt.json": '{"passed":true}\n'},
    )
    write_json(handoff / "evidence/case-archive-manifest.json", case)
    write_json(
        handoff / "evidence/case-members.json",
        {
            "source_sha": "a" * 40,
            "run_id": "456",
            "run_attempt": "1",
            "case_indices": [1],
            "present_case_indices": [1],
        },
    )

    def download(manifest: dict[str, Any], **kwargs: Any) -> Path:
        return archives[manifest["archive_sha256"]]

    monkeypatch.setattr(release_evidence, "download_archive", download)
    monkeypatch.chdir(checkout)
    for key, value in {
        "RUNNER_TEMP": str(temporary),
        "BUNDLE_ROOT": str(root),
        "SEED_MANIFEST_FILE": "installation-seed.json",
        "CASE_INDICES_JSON": "[1]",
        "GITHUB_RUN_ID": "456",
        "SOURCE_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    return {
        "root": root,
        "handoff": handoff,
        "originals": originals,
        "artifacts": artifacts,
        "make_archive": make_archive,
    }


def test_case_overlay_uses_new_staging_then_preserves_seed(restored: dict[str, Any]) -> None:
    exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})
    root = restored["root"]
    assert (root / "inputs/original.json").read_bytes() == b'{"original":true}\n'
    assert json.loads((root / "installations/restart-v2/case-0001/case-receipt.json").read_bytes())


def test_case_overlay_rejects_another_case_archive(restored: dict[str, Any]) -> None:
    # 原件的归档可安全解包，但其当项目录身份仍必须与 matrix 相同。
    restored["handoff"].rename(restored["handoff"].with_name("installation-case-456-2"))
    with pytest.raises(AssertionError):
        exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})
    assert (restored["root"] / "inputs/original.json").read_bytes() == b'{"original":true}\n'


def test_case_archive_cannot_replace_original_inputs(restored: dict[str, Any]) -> None:
    manifest = restored["make_archive"]("out-of-case", {"inputs/original.json": "changed"})
    write_json(restored["handoff"] / "evidence/case-archive-manifest.json", manifest)
    with pytest.raises(ValueError, match="越界"):
        exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})
    assert (restored["root"] / "inputs/original.json").read_bytes() == b'{"original":true}\n'


def test_partial_seed_cannot_reuse_stale_preflight(restored: dict[str, Any]) -> None:
    manifest = restored["make_archive"](
        "stale", {"installations/restart-v2/preflight.json": '{"passed":true}'}
    )
    write_json(restored["artifacts"] / "installation-seed.json", manifest)
    with pytest.raises(ValueError, match="本阶段输出"):
        exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})


def test_bounded_fallback_restores_same_native_case(restored: dict[str, Any]) -> None:
    handoff = restored["handoff"]
    (handoff / "evidence/case-archive-manifest.json").unlink()
    archive = handoff / "case.tar.gz"
    archive.write_bytes((restored["originals"] / "case.tar.gz").read_bytes())
    write_json(
        handoff / "evidence/retention-fallback.json",
        {
            "passed": True,
            "fallback_ready": True,
            "archive": {"sha256": file_sha256(archive), "size_in_bytes": archive.stat().st_size},
        },
    )
    exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})
    assert (restored["root"] / "installations/restart-v2/case-0001/case-receipt.json").is_file()


def test_workflow_has_no_model_secret_and_pins_actions() -> None:
    value = workflow()
    assert "secrets." not in TEMPLATE.read_text(encoding="utf-8")
    for name, job in value["jobs"].items():
        assert int(job["timeout-minutes"]) <= (120 if name == "case" else 55)
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[A-Za-z0-9_./-]+@[0-9a-f]{40}", step["uses"])
            if "GH_TOKEN" in step.get("env", {}):
                assert step.get("id") != "native"
    native = next(step for step in value["jobs"]["case"]["steps"] if step.get("id") == "native")
    assert "env -u GH_TOKEN -u GITHUB_TOKEN -u SAYACODE_STUDY_CONNECTION_KEYS_JSON" in native["run"]
    assert value["jobs"]["case"]["strategy"]["fail-fast"] == "false"
    assert value["jobs"]["merge"]["needs"] == ["plan", "case"]
    assert "needs.plan.outputs.ready == 'true'" in value["jobs"]["case"]["if"]


@pytest.mark.parametrize("remaining,ready", [(999, True), (949, False), (0, False)])
def test_quota_admission_never_starts_native_when_low(
    guarded: None, tmp_path: Path, monkeypatch: Any, remaining: int, ready: bool
) -> None:
    monkeypatch.setenv("CASE_INDICES_JSON", json.dumps(list(range(1, 47))))
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def response(arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        assert arguments == ["gh", "api", "repos/saya-ch/sayacode-bench-runs", "--include"]
        headers = (
            f"HTTP/2.0 200 OK\r\nx-ratelimit-limit: 1000\r\n"
            f"x-ratelimit-remaining: {remaining}\r\nx-ratelimit-reset: 1234567890\r\n\r\n"
        )
        project = {"id": 1429748203, "private": True, "full_name": "saya-ch/sayacode-bench-runs"}
        return SimpleNamespace(stdout=(headers + json.dumps(project)).encode())

    monkeypatch.setattr(subprocess, "run", response)
    exec(compile(body("plan", "核对配额并按两项划分原生矩阵"), str(TEMPLATE), "exec"), {})
    report = json.loads((tmp_path / "admission/quota.json").read_bytes())
    assert report["ready"] is ready and report["native_cases_started"] == 0
    assert len(report["groups"]) == 23
    assert [index for group in report["groups"] for index in group["case_indices"]] == list(
        range(1, 47)
    )
    assert f"ready={str(ready).lower()}" in output.read_text(encoding="utf-8")


def test_handoff_staging_has_explicit_nested_evidence(tmp_path: Path, monkeypatch: Any) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    write_json(evidence / "case-members.json", {"case_indices": [1, 2]})
    archive = tmp_path / "case.tar.gz"
    archive.write_bytes(b"checked bounded raw archive")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("FALLBACK_READY", "true")
    exec(compile(body("case", "以固定目录结构整理交接"), str(TEMPLATE), "exec"), {})
    assert (tmp_path / "handoff/evidence/case-members.json").read_bytes() == (
        evidence / "case-members.json"
    ).read_bytes()
    assert (tmp_path / "handoff/case.tar.gz").read_bytes() == archive.read_bytes()
    upload = next(
        step
        for step in workflow()["jobs"]["case"]["steps"]
        if step.get("name") == "私有小型交接或未确认现场"
    )
    assert upload["with"]["path"] == "${{ runner.temp }}/handoff"


def test_two_case_archive_restores_both_without_copying_history(
    restored: dict[str, Any], monkeypatch: Any
) -> None:
    manifest = restored["make_archive"](
        "pair",
        {
            f"installations/restart-v2/case-{index:04d}/case-receipt.json": '{"passed":true}'
            for index in (1, 2)
        },
    )
    handoff = restored["handoff"]
    write_json(handoff / "evidence/case-archive-manifest.json", manifest)
    members = json.loads((handoff / "evidence/case-members.json").read_bytes())
    members.update(case_indices=[1, 2], present_case_indices=[1, 2])
    write_json(handoff / "evidence/case-members.json", members)
    monkeypatch.setenv("CASE_INDICES_JSON", "[1,2]")
    exec(compile(body("merge", "恢复全部原始安装现场"), str(TEMPLATE), "exec"), {})
    for index in (1, 2):
        assert (
            restored["root"] / f"installations/restart-v2/case-{index:04d}/case-receipt.json"
        ).is_file()


@pytest.mark.parametrize("failed_indices", [[], [1], [2], [1, 2]])
def test_two_case_step_keeps_separate_cli_outputs_and_continues_after_failure(
    guarded: None, tmp_path: Path, monkeypatch: Any, failed_indices: list[int]
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    monkeypatch.setenv("BUNDLE_ROOT", str(root))
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    calls: list[list[str]] = []

    def invoke(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        assert kwargs == {"check": False}
        assert arguments[1:4] == ["-m", "scripts.preflight_installations", "run"]
        calls.append(arguments)
        Path(arguments[arguments.index("--output") + 1]).mkdir(parents=True)
        index = int(arguments[arguments.index("--case-index") + 1])
        return subprocess.CompletedProcess(arguments, int(index in failed_indices))

    monkeypatch.setattr(subprocess, "run", invoke)
    code = compile(
        body("case", "原生 install_only；不执行 Agent 或 verifier"), str(TEMPLATE), "exec"
    )
    if failed_indices:
        with pytest.raises(SystemExit) as stopped:
            exec(code, {})
        assert stopped.value.code == 1
    else:
        exec(code, {})
    assert [arguments[arguments.index("--case-index") + 1] for arguments in calls] == ["1", "2"]
    for index in (1, 2):
        assert (root / f"installations/restart-v2/case-{index:04d}").is_dir()
        marker = json.loads((tmp_path / f"evidence/native-attempt-{index:04d}.json").read_bytes())
        assert marker["CASE_INDEX"] == str(index)
    assert json.loads((tmp_path / "evidence/native-exit-codes.json").read_bytes()) == [
        {"case_index": index, "exit_code": int(index in failed_indices)} for index in (1, 2)
    ]


def test_missing_case_outputs_still_produce_partial_diagnostic(
    restored: dict[str, Any], monkeypatch: Any
) -> None:
    from scripts import preflight_installations

    restored["root"].mkdir()
    observed: list[list[Path]] = []

    def merge(inputs: Path, source: str, receipts: list[Path], output: Path) -> dict[str, bool]:
        observed.append(receipts)
        write_json(output, {"complete": False, "passed": False}, exclusive=True)
        return {"complete": False, "passed": False}

    monkeypatch.setattr(preflight_installations, "merge_cases", merge)
    exec(compile(body("merge", "严格合并四十六项；部分回归仅保留诊断"), str(TEMPLATE), "exec"), {})
    assert observed == [[]]
    assert (restored["root"] / "installations/restart-v2/preflight.json").is_file()


def test_all_embedded_python_blocks_compile() -> None:
    count = 0
    for job in workflow()["jobs"].values():
        for step in job["steps"]:
            for script in re.findall(
                r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", step.get("run", ""), re.DOTALL
            ):
                compile(script, str(TEMPLATE), "exec")
                count += 1
    assert count >= 5
