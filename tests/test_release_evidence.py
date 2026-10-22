"""模拟官方 gh CLI 与真实二进制分片；不访问 GitHub 或任何凭据。"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sayacode_bench import release_evidence as module

RELEASE = 44
TAG = "private-study-evidence"


class FakeGh:
    def __init__(self) -> None:
        self.project = {
            "id": 7,
            "full_name": module.REPOSITORY,
            "private": True,
            "visibility": "private",
        }
        self.release = {"id": RELEASE, "tag_name": TAG, "draft": True}
        self.assets: dict[int, dict[str, Any]] = {}
        self.bodies: dict[int, bytes] = {}
        self.calls: list[list[str]] = []
        self.uploads = 0
        self.bad_upload_digest = False
        self.fail_download = False
        self.public_after_upload = False

    def run(self, command: list[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append(command)
        assert command[:2] == ["gh", "api"]
        assert command[command.index("--hostname") + 1] == "github.com"
        assert "env" not in kwargs
        assert not any(word in " ".join(command) for word in ("--clobber", "DELETE", "token-value"))
        assert kwargs["check"] is False and kwargs["timeout"] > 0
        endpoint = command[2].removeprefix("https://uploads.github.com/")
        prefix = f"repos/{module.REPOSITORY}"
        if endpoint == prefix:
            value: Any = self.project
        elif endpoint == prefix + f"/releases/{RELEASE}":
            value = self.release
        elif endpoint == prefix + f"/releases/{RELEASE}/assets?per_page=100":
            assert "--paginate" in command and "--slurp" in command
            value = [list(self.assets.values())]
        elif endpoint.startswith(prefix + f"/releases/{RELEASE}/assets?name="):
            assert command[command.index("--method") + 1] == "POST"
            path = Path(command[command.index("--input") + 1])
            with path.open("rb") as stream:
                body = stream.read()
            asset_id = 100 + len(self.assets)
            value = {
                "id": asset_id,
                "name": endpoint.split("?name=", 1)[1],
                "size": len(body),
                "state": "uploaded",
                "digest": "sha256:"
                + ("0" * 64 if self.bad_upload_digest else hashlib.sha256(body).hexdigest()),
            }
            self.assets[asset_id], self.bodies[asset_id] = value, body
            self.uploads += 1
            if self.public_after_upload:
                self.project["private"] = False
        elif endpoint.startswith(prefix + "/releases/assets/"):
            asset_id = int(endpoint.rsplit("/", 1)[1])
            if "Accept: application/octet-stream" in command:
                assert kwargs["stdout"] is not subprocess.PIPE
                if self.fail_download:
                    return SimpleNamespace(returncode=1, stdout=None, stderr=b"private-server-body")
                kwargs["stdout"].write(self.bodies[asset_id])
                return SimpleNamespace(returncode=0, stdout=None, stderr=b"")
            value = self.assets[asset_id]
        else:
            pytest.fail(f"意外的 CLI 调用：{command[:3]}")
        assert kwargs["stdout"] is subprocess.PIPE
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b"")


@pytest.fixture
def server(monkeypatch: Any) -> FakeGh:
    result = FakeGh()
    monkeypatch.setattr(module.subprocess, "run", result.run)
    return result


def upload(tmp_path: Path, *, work: str = "parts", **kwargs: Any) -> dict[str, Any]:
    source = tmp_path / "original.tar.gz"
    if not source.exists():
        with source.open("wb") as stream:
            stream.write(bytes(range(256)) * 5 + b"\0tail\xff")
    return module.upload_archive(
        source,
        repository=module.REPOSITORY,
        release_id=RELEASE,
        release_tag=TAG,
        work_dir=tmp_path / work,
        part_size_bytes=257,
        **kwargs,
    )


def download(manifest: dict[str, Any], output: Path) -> Path:
    return module.download_archive(
        manifest,
        repository=module.REPOSITORY,
        release_id=RELEASE,
        release_tag=TAG,
        output_dir=output,
    )


def test_binary_parts_round_trip_and_manifest_bind_complete_archive(
    tmp_path: Path, server: FakeGh
) -> None:
    manifest = upload(tmp_path)
    target = download(manifest, tmp_path / "received")
    with target.open("rb") as result, (tmp_path / "original.tar.gz").open("rb") as original:
        assert result.read() == original.read()
    assert len(manifest["parts"]) == server.uploads == 6
    assert [part["number"] for part in manifest["parts"]] == list(range(1, 7))
    assert all(part["size"] <= 257 < 2 * 1024**3 for part in manifest["parts"])
    assert sum(part["size"] for part in manifest["parts"]) == manifest["archive_size"]
    assert all(part["service_digest"] == "sha256:" + part["sha256"] for part in manifest["parts"])
    assert manifest["repository_id"] == 7
    assert manifest["guaranteed_free_forever"] is manifest["account_budget_changed"] is False
    assert manifest["actions_compute_minutes_still_apply"] is True
    assert "不是永久免费" in manifest["billing_boundary"]
    assert not any("extract" in " ".join(call) for call in server.calls)


def test_existing_same_bytes_are_idempotent_without_overwrite(
    tmp_path: Path, server: FakeGh
) -> None:
    first = upload(tmp_path)
    uploads = server.uploads
    second = upload(tmp_path, work="retry-parts")
    assert second == first
    assert server.uploads == uploads
    assert not any("DELETE" in call or "--clobber" in call for call in server.calls)


@pytest.mark.parametrize(
    "field,value", [("digest", "sha256:" + "0" * 64), ("size", 1), ("state", "starter")]
)
def test_existing_name_with_conflicting_facts_is_never_replaced(
    tmp_path: Path, server: FakeGh, field: str, value: Any
) -> None:
    manifest = upload(tmp_path)
    server.assets[manifest["parts"][0]["asset_id"]][field] = value
    count = server.uploads
    with pytest.raises(module.ReleaseEvidenceError, match="冲突"):
        upload(tmp_path, work="second")
    assert server.uploads == count


@pytest.mark.parametrize("kind", ["public", "visibility", "release", "tag", "published"])
def test_live_private_and_fixed_draft_guard_prevents_upload(
    tmp_path: Path, server: FakeGh, kind: str
) -> None:
    if kind == "public":
        server.project["private"] = False
    elif kind == "visibility":
        server.project["visibility"] = "public"
    elif kind == "release":
        server.release["id"] = RELEASE + 1
    elif kind == "tag":
        server.release["tag_name"] = "other"
    else:
        server.release["draft"] = False
    with pytest.raises(module.ReleaseEvidenceError, match="draft"):
        upload(tmp_path)
    assert server.uploads == 0 and not (tmp_path / "parts").exists()


def test_private_guard_runs_again_before_next_part(tmp_path: Path, server: FakeGh) -> None:
    server.public_after_upload = True
    with pytest.raises(module.ReleaseEvidenceError, match="私有性"):
        upload(tmp_path)
    assert server.uploads == 1 and not (tmp_path / "parts/manifest.json").exists()


@pytest.mark.parametrize(
    "repository,release_id,tag",
    [
        ("other/repository", RELEASE, TAG),
        (module.REPOSITORY, 0, TAG),
        (module.REPOSITORY, True, TAG),
        (module.REPOSITORY, RELEASE, "bad\ntag"),
    ],
)
def test_io_scope_rejected_before_any_cli(
    tmp_path: Path, server: FakeGh, repository: str, release_id: int, tag: str
) -> None:
    with pytest.raises(module.ReleaseEvidenceError):
        module.upload_archive(
            tmp_path / "source",
            repository=repository,
            release_id=release_id,
            release_tag=tag,
            work_dir=tmp_path / "new",
        )
    assert not server.calls


@pytest.mark.parametrize("size", [0, -1, True, module.MAX_PART_SIZE + 1])
def test_parts_never_exceed_one_gib(tmp_path: Path, server: FakeGh, size: int) -> None:
    source = tmp_path / "source"
    source.write_text("offline", encoding="utf-8")
    with pytest.raises(module.ReleaseEvidenceError, match="1 GiB"):
        module.upload_archive(
            source,
            repository=module.REPOSITORY,
            release_id=RELEASE,
            release_tag=TAG,
            work_dir=tmp_path / "parts",
            part_size_bytes=size,
        )
    assert server.uploads == 0


def test_upload_requires_actual_service_digest(tmp_path: Path, server: FakeGh) -> None:
    server.bad_upload_digest = True
    with pytest.raises(module.ReleaseEvidenceError, match="digest"):
        upload(tmp_path)
    assert server.uploads == 1 and not (tmp_path / "parts/manifest.json").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "order",
        "duplicate",
        "name",
        "part_sha",
        "total_size",
        "release",
        "repo_id",
        "service_digest",
    ],
)
def test_download_manifest_conflicts_fail_closed(tmp_path: Path, server: FakeGh, kind: str) -> None:
    manifest = upload(tmp_path)
    changed = copy.deepcopy(manifest)
    if kind == "order":
        changed["parts"].reverse()
    elif kind == "duplicate":
        changed["parts"][1]["asset_id"] = changed["parts"][0]["asset_id"]
    elif kind == "name":
        changed["parts"][0]["name"] = "../outside.bin"
    elif kind == "part_sha":
        changed["parts"][0]["sha256"] = "0" * 64
    elif kind == "total_size":
        changed["archive_size"] += 1
    elif kind == "release":
        changed["release_id"] += 1
    elif kind == "repo_id":
        changed["repository_id"] += 1
    else:
        changed["parts"][0]["service_digest"] = None
    with pytest.raises(module.ReleaseEvidenceError):
        download(changed, tmp_path / "bad")
    assert not (tmp_path / "bad/bundle.tar.gz").exists()


@pytest.mark.parametrize("kind", ["body", "size", "digest", "membership", "failure", "archive_sha"])
def test_download_verifies_bytes_metadata_membership_and_complete_tar(
    tmp_path: Path, server: FakeGh, kind: str
) -> None:
    manifest = upload(tmp_path)
    asset_id = manifest["parts"][0]["asset_id"]
    if kind == "body":
        server.bodies[asset_id] = b"!" * len(server.bodies[asset_id])
    elif kind == "size":
        server.bodies[asset_id] += b"extra"
    elif kind == "digest":
        server.assets[asset_id]["digest"] = None
    elif kind == "membership":
        server.assets.pop(asset_id)
    elif kind == "failure":
        server.fail_download = True
    else:
        manifest["archive_sha256"] = "0" * 64
        for part in manifest["parts"]:
            part["name"] = module._name(
                "0" * 64, part["number"], len(manifest["parts"]), part["sha256"]
            )
            server.assets[part["asset_id"]]["name"] = part["name"]
    with pytest.raises(module.ReleaseEvidenceError):
        download(manifest, tmp_path / "bad")
    assert not (tmp_path / "bad/bundle.tar.gz").exists()


def test_streaming_does_not_call_path_read_bytes_or_extract(
    tmp_path: Path, server: FakeGh, monkeypatch: Any
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("完整 tar/分片必须流式读写")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    manifest = upload(tmp_path)
    assert download(manifest, tmp_path / "received").is_file()


def test_gh_failure_does_not_expose_stderr_or_read_credentials(
    tmp_path: Path, server: FakeGh, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-value")
    manifest = upload(tmp_path)
    server.fail_download = True
    with pytest.raises(module.ReleaseEvidenceError) as error:
        download(manifest, tmp_path / "bad")
    assert "private-server-body" not in str(error.value) and "token-value" not in str(error.value)


def test_existing_local_directories_are_not_overwritten(tmp_path: Path, server: FakeGh) -> None:
    manifest = upload(tmp_path)
    with pytest.raises(FileExistsError):
        upload(tmp_path)
    target = tmp_path / "received"
    target.mkdir()
    with pytest.raises(FileExistsError):
        download(manifest, target)
