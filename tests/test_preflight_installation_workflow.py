"""执行模板中的真实输入检查与安全归档恢复；不调用 GitHub 或模型。"""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
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
    handoff.mkdir(parents=True)
    case = make_archive(
        "case",
        {"installations/restart-v2/case-0001/case-receipt.json": '{"passed":true}\n'},
    )
    write_json(handoff / "case-archive-manifest.json", case)

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
    write_json(restored["handoff"] / "case-archive-manifest.json", manifest)
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
    (handoff / "case-archive-manifest.json").unlink()
    archive = handoff / "case.tar.gz"
    archive.write_bytes((restored["originals"] / "case.tar.gz").read_bytes())
    write_json(
        handoff / "retention-fallback.json",
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
    for job in value["jobs"].values():
        assert int(job["timeout-minutes"]) < 60
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[A-Za-z0-9_./-]+@[0-9a-f]{40}", step["uses"])
            if "GH_TOKEN" in step.get("env", {}):
                assert "scripts.preflight_installations run" not in step.get("run", "")
    native = next(
        step
        for step in value["jobs"]["case"]["steps"]
        if "scripts.preflight_installations run" in step.get("run", "")
    )
    assert "env -u GH_TOKEN -u GITHUB_TOKEN -u SAYACODE_STUDY_CONNECTION_KEYS_JSON" in native["run"]
    assert value["jobs"]["case"]["strategy"]["fail-fast"] == "false"
    assert value["jobs"]["merge"]["needs"] == "case"


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
