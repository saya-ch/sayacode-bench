"""固定四项安装 fallback 的存储边界；测试不访问 GitHub。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import preflight_installation_storage as storage


def artifact(identity: int, size: int, *, expired: bool = False) -> dict[str, Any]:
    return {"id": identity, "size_in_bytes": size, "expired": expired}


def pages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"total_count": len(items), "artifacts": items[i : i + 100]}
        for i in range(0, max(1, len(items)), 100)
    ]


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    data: dict[str, Any] = {
        "repo": {
            "id": storage.PRIVATE_ID,
            "full_name": storage.PRIVATE,
            "private": True,
            "visibility": "private",
        },
        "public": pages([]),
        "private": pages([]),
        "calls": [],
    }

    def get(endpoint: str, *, paginate: bool = False) -> Any:
        data["calls"].append((endpoint, paginate))
        if endpoint == f"repos/{storage.PRIVATE}":
            assert not paginate
            return data["repo"]
        assert paginate
        if endpoint == f"repos/{storage.PUBLIC}/actions/artifacts?per_page=100":
            return data["public"]
        assert endpoint == f"repos/{storage.PRIVATE}/actions/artifacts?per_page=100"
        return data["private"]

    monkeypatch.setattr(storage, "_get", get)
    return data


def test_four_concurrent_fallbacks_block_old_guard_pass(service: dict[str, Any]) -> None:
    service["public"] = pages([artifact(1, 140_000_000)])
    service["private"] = pages([artifact(2, 125_000_000)])
    report = storage.check_storage("reserve")
    assert 140_000_000 + 125_000_000 + 50_000_000 <= 330_000_000
    assert report["projected_bytes"] == 355_000_000
    assert report["concurrent_raw_fallback_reserve_bytes"] == 40_000_000
    assert report["status"] == "retention_unconfirmed" and report["passed"] is False


@pytest.mark.parametrize(
    "public,private,expected",
    [
        (155_000_000, 0, True),
        (155_000_001, 0, False),
        (115_000_000, 125_000_000, True),
        (115_000_001, 125_000_000, False),
    ],
)
def test_exact_330mb_boundary(
    service: dict[str, Any], public: int, private: int, expected: bool
) -> None:
    service["public"] = pages([artifact(1, public)])
    service["private"] = pages([artifact(2, private)])
    result = storage.check_storage("reserve")
    assert result["passed"] is expected
    assert result["fallback_ready"] is False
    assert result["retention_confirmed"] is False


def test_complete_pagination_and_expired_exclusion(service: dict[str, Any]) -> None:
    service["public"] = pages(
        [artifact(i + 1, 1000) for i in range(150)] + [artifact(151, 999_000_000, expired=True)]
    )
    result = storage.check_storage("reserve")
    assert result["passed"] is True and result["public_actual_bytes"] == 150_000
    assert result["inventories"][0]["pages"] == 2
    assert result["inventories"][0]["total_count"] == 151
    assert result["inventories"][0]["active_count"] == 150


@pytest.mark.parametrize(
    "kind",
    [
        "truncated",
        "duplicate",
        "changed_total",
        "short_first_page",
        "empty_pages",
        "bad_size",
        "bad_expired",
        "boolean_count",
    ],
)
def test_unconfirmed_pagination_never_passes(service: dict[str, Any], kind: str) -> None:
    value = pages([artifact(i + 1, 1) for i in range(101)])
    if kind == "truncated":
        value.pop()
    elif kind == "duplicate":
        value[-1]["artifacts"][0]["id"] = 1
    elif kind == "changed_total":
        value[-1]["total_count"] = 102
    elif kind == "short_first_page":
        value[1]["artifacts"].insert(0, value[0]["artifacts"].pop())
    elif kind == "empty_pages":
        value = []
    elif kind == "bad_size":
        value[0]["artifacts"][0]["size_in_bytes"] = -1
    elif kind == "bad_expired":
        value[0]["artifacts"][0]["expired"] = None
    else:
        value[0]["total_count"] = True
    service["public"] = value
    report = storage.check_storage("reserve")
    assert report["passed"] is False and report["status"] == "retention_unconfirmed"


@pytest.mark.parametrize(
    "field,value",
    [("private", False), ("visibility", "public"), ("id", 1), ("full_name", "other/repository")],
)
def test_private_identity_rejected_before_listing(
    service: dict[str, Any], field: str, value: Any
) -> None:
    service["repo"][field] = value
    result = storage.check_storage("reserve")
    assert result["passed"] is False
    assert service["calls"] == [(f"repos/{storage.PRIVATE}", False)]


def test_fallback_rechecks_guard_and_hashes_file(service: dict[str, Any], tmp_path: Path) -> None:
    archive = tmp_path / "case.tar.gz"
    archive.write_bytes(b"raw compressed evidence")
    report = storage.check_storage("fallback", archive)
    assert report["passed"] is True and report["fallback_ready"] is True
    assert report["archive"]["sha256"] == storage.file_sha256(archive)
    assert report["retention_confirmed"] is False
    assert len(service["calls"]) == 3
    service["public"] = pages([artifact(1, 156_000_000)])
    assert storage.check_storage("fallback", archive)["fallback_ready"] is False


@pytest.mark.parametrize("size,passed", [(0, False), (10_000_000, True), (10_000_001, False)])
def test_fallback_size_cap(
    service: dict[str, Any], tmp_path: Path, size: int, passed: bool
) -> None:
    archive = tmp_path / "case.tar.gz"
    with archive.open("wb") as stream:
        stream.truncate(size)
    report = storage.check_storage("fallback", archive)
    assert report["passed"] is passed and report["fallback_ready"] is passed
    if not passed:
        assert not service["calls"]
        assert archive.stat().st_size == size


def test_fallback_not_a_directory(service: dict[str, Any], tmp_path: Path) -> None:
    result = storage.check_storage("fallback", tmp_path)
    assert not result["passed"] and not service["calls"]


def test_changed_archive_during_get_is_unconfirmed(
    service: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "case.tar.gz"
    archive.write_bytes(b"before")
    original = storage._guard

    def guard() -> dict[str, Any]:
        value = original()
        archive.write_bytes(b"after!")
        return value

    monkeypatch.setattr(storage, "_guard", guard)
    result = storage.check_storage("fallback", archive)
    assert result["passed"] is False and "改变" in result["reason"]


def test_cli_failure_preserves_small_retention_diagnostic(
    service: dict[str, Any], tmp_path: Path
) -> None:
    archive, output = tmp_path / "case.tar.gz", tmp_path / "fallback.json"
    with archive.open("wb") as stream:
        stream.truncate(10_000_001)
    assert storage.main(["fallback", "--archive", str(archive), "--output", str(output)]) == 2
    report = json.loads(output.read_bytes())
    assert report["status"] == "retention_unconfirmed" and report["fallback_ready"] is False
    assert report["retention_confirmed"] is False and archive.is_file()
    assert output.stat().st_size < 2000


def test_cli_pass_does_not_claim_upload(service: dict[str, Any], tmp_path: Path) -> None:
    output = tmp_path / "reserve.json"
    assert storage.main(["reserve", "--output", str(output)]) == 0
    report = json.loads(output.read_bytes())
    assert report["passed"] is True and report["retention_confirmed"] is False
    assert report["deletion_performed"] is False and report["billing_settings_changed"] is False
    old = output.read_bytes()
    assert storage.main(["reserve", "--output", str(output)]) == 2
    assert output.read_bytes() == old


@pytest.mark.parametrize("outcome", ["nonzero", "bad_json", "timeout"])
def test_gh_read_failure_is_not_zero_inventory(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert arguments[:2] == ["gh", "api"]
        assert arguments[arguments.index("--method") + 1] == "GET"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(arguments, 60)
        return subprocess.CompletedProcess(
            arguments, 1 if outcome == "nonzero" else 0, b"not-json", b"opaque error"
        )

    monkeypatch.setattr(storage.subprocess, "run", run)
    report = storage.check_storage("reserve")
    assert report["passed"] is False and "public_actual_bytes" not in report
    assert "opaque error" not in json.dumps(report)


def test_only_fixed_gets_and_complete_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        assert arguments[arguments.index("--method") + 1] == "GET"
        endpoint = arguments[2]
        if endpoint == f"repos/{storage.PRIVATE}":
            data: Any = {
                "id": storage.PRIVATE_ID,
                "full_name": storage.PRIVATE,
                "private": True,
                "visibility": "private",
            }
        else:
            assert endpoint in {
                f"repos/{repo}/actions/artifacts?per_page=100"
                for repo in (storage.PUBLIC, storage.PRIVATE)
            }
            assert "--paginate" in arguments and "--slurp" in arguments
            data = pages([])
        return subprocess.CompletedProcess(arguments, 0, json.dumps(data).encode(), b"")

    monkeypatch.setattr(storage.subprocess, "run", run)
    assert storage.check_storage("reserve")["passed"] is True
    assert len(calls) == 3
