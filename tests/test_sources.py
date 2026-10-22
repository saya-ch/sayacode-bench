"""公开数据身份、换行转换和不可信归档的行为检查。"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from sayacode_bench.sources import (
    SourceSpec,
    _extract_archive,
    build_catalog,
    fetch_source,
    verify_checksums,
)


def _repository(root: Path) -> tuple[Path, SourceSpec]:
    repository = root / "repository"
    task = repository / "tasks" / "sample"
    task.mkdir(parents=True)
    (repository / "LICENSE").write_bytes(b"MIT License\n")
    (task / "instruction.md").write_bytes(b"Implement the stated behavior.\n")
    (task / "task.toml").write_text(
        '[metadata]\ncategory="debugging"\ndifficulty="medium"\ntags=["python"]\n'
        '[environment]\ndocker_image="example/task:fixed"\ncpus=1\nmemory_mb=2048\n'
        "[agent]\ntimeout_sec=900\n[verifier]\ntimeout_sec=600\n",
        encoding="utf-8",
        newline="\n",
    )
    (task / "solution").mkdir()
    (task / "solution" / "answer.txt").write_text("PRIVATE ORACLE ANSWER", encoding="utf-8")
    instruction = task / "instruction.md"
    expected = hashlib.sha256(instruction.read_bytes()).hexdigest()
    (repository / "SHA256SUMS").write_text(
        f"{expected}  tasks/sample/instruction.md\n", encoding="utf-8", newline="\n"
    )
    for arguments in (
        ["init"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@example.invalid"],
        ["config", "core.autocrlf", "false"],
        ["add", "."],
        ["commit", "-m", "fixture"],
    ):
        subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)
    revision = (
        subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    return repository, SourceSpec(
        "fixture", "https://example.invalid/fixture.git", revision, "tasks", "MIT", "SHA256SUMS"
    )


def test_fetch_uses_git_blobs_not_crlf_checkout(tmp_path: Path) -> None:
    repository, spec = _repository(tmp_path)
    path = repository / "tasks" / "sample" / "instruction.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    snapshot = fetch_source(spec, tmp_path / "cache", local_repository=repository)
    assert snapshot.checksums_verified == 1
    assert (snapshot.tasks_path / "sample" / "instruction.md").read_bytes().endswith(b".\n")
    assert b"\r\n" not in (snapshot.tasks_path / "sample" / "instruction.md").read_bytes()
    assert fetch_source(spec, tmp_path / "cache").archive_sha256 == snapshot.archive_sha256


def test_cache_edit_is_rejected(tmp_path: Path) -> None:
    repository, spec = _repository(tmp_path)
    snapshot = fetch_source(spec, tmp_path / "cache", local_repository=repository)
    (snapshot.path / "LICENSE").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="快照文件已被修改"):
        fetch_source(spec, tmp_path / "cache")


def test_catalog_preserves_resources_without_exposing_oracle(tmp_path: Path) -> None:
    repository, spec = _repository(tmp_path)
    snapshot = fetch_source(spec, tmp_path / "cache", local_repository=repository)
    catalog = build_catalog(snapshot)
    assert len(catalog) == 1
    record = catalog[0]
    assert record.environment == {
        "docker_image": "example/task:fixed",
        "cpus": 1,
        "memory_mb": 2048,
    }
    assert record.agent == {"timeout_sec": 900}
    assert record.language == "python"
    assert record.has_custom_compose is False
    payload = json.dumps(record.public_dict())
    assert "PRIVATE ORACLE ANSWER" not in payload
    assert "answer.txt" not in payload
    assert str(tmp_path) not in payload


@pytest.mark.parametrize("filename", ["docker-compose.yaml", "docker-compose.yml"])
def test_catalog_identifies_custom_compose_before_running_models(
    tmp_path: Path, filename: str
) -> None:
    repository, spec = _repository(tmp_path)
    environment = repository / "tasks" / "sample" / "environment"
    environment.mkdir()
    (environment / filename).write_text(
        "services:\n  sidecar:\n    image: example/sidecar:fixed\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "compose fixture"],
        check=True,
        capture_output=True,
    )
    revision = (
        subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    snapshot = fetch_source(
        replace(spec, revision=revision), tmp_path / "cache", local_repository=repository
    )
    assert build_catalog(snapshot)[0].has_custom_compose is True


def test_checksum_is_strict_about_crlf(tmp_path: Path) -> None:
    content = b"first\nsecond\n"
    (tmp_path / "file").write_bytes(content.replace(b"\n", b"\r\n"))
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(f"{hashlib.sha256(content).hexdigest()}  file\n", encoding="utf-8")
    with pytest.raises(ValueError, match="换行转换"):
        verify_checksums(tmp_path, manifest)


@pytest.mark.parametrize(
    "relative", ["../outside", "/absolute", "nested/../../outside", "nested\\outside"]
)
def test_checksum_rejects_escape(tmp_path: Path, relative: str) -> None:
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(f"{'0' * 64}  {relative}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="路径"):
        verify_checksums(tmp_path, manifest)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "escape"])
def test_archive_rejects_unsafe_members(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "archive.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("../outside" if kind == "escape" else "link")
        if kind in ("symlink", "hardlink"):
            member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "../outside"
        else:
            member.size = 3
        bundle.addfile(member, io.BytesIO(b"bad") if kind == "escape" else None)
    destination = tmp_path / "snapshot"
    destination.mkdir()
    with pytest.raises(ValueError):
        _extract_archive(archive, destination)
    assert not (tmp_path / "outside").exists()


def test_source_requires_pinned_revision(tmp_path: Path) -> None:
    spec = SourceSpec("fixture", "https://example.invalid/repo.git", "main", "tasks", "MIT")
    with pytest.raises(ValueError, match="完整"):
        fetch_source(spec, tmp_path)
