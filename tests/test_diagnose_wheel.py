"""只允许逐字节证实的 made-by OS 差异，不能由 payload 相同推断可放行。"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.diagnose_wheel import compare_wheels, main


def wheel(path: Path, *, system=0, entries=None, attributes=0o100644 << 16, comment=b""):
    with zipfile.ZipFile(path, "w") as archive:
        archive.comment = comment
        for name, payload in entries or [
            ("package/__init__.py", b"content"),
            ("package/data.bin", b"\x00\xff"),
        ]:
            info = zipfile.ZipInfo(name, (2020, 1, 2, 3, 4, 6))
            info.create_system = system
            info.external_attr = attributes
            archive.writestr(info, payload)
    return path


def test_windows_to_linux_os_bytes_are_the_only_allowed_difference(tmp_path):
    original, rebuilt = wheel(tmp_path / "original.whl"), wheel(tmp_path / "rebuilt.whl", system=3)
    before = original.read_bytes(), rebuilt.read_bytes()
    report = compare_wheels(original, rebuilt)
    assert report["allowed"] and report["payload_equal"]
    assert report["entry_count"] == report["rebuilt_entry_count"] == 2
    assert (
        report["archive_byte_difference_count"]
        == report["allowed_create_system_difference_count"]
        == 2
    )
    assert report["unexpected_archive_difference_count"] == 0
    assert all(
        row["field"] == "create_system" and row["allowed"] for row in report["metadata_differences"]
    )
    assert (original.read_bytes(), rebuilt.read_bytes()) == before


def test_identical_archive_is_accepted_without_claiming_os_differences(tmp_path):
    original = wheel(tmp_path / "original.whl")
    report = compare_wheels(original, original)
    assert report["allowed"] and report["archive_byte_difference_count"] == 0
    assert report["metadata_differences"] == []
    assert report["original_sha256"] == report["rebuilt_sha256"]


def test_same_payload_in_a_different_order_is_rejected(tmp_path):
    first = [("a", b"alpha"), ("b", b"beta")]
    report = compare_wheels(
        wheel(tmp_path / "a.whl", entries=first),
        wheel(tmp_path / "b.whl", system=3, entries=list(reversed(first))),
    )
    assert report["payload_equal"] and report["names_equal"]
    assert not report["order_equal"] and not report["allowed"]


def test_payload_changes_are_not_os_metadata_normalization(tmp_path):
    report = compare_wheels(
        wheel(tmp_path / "a.whl", entries=[("a", b"PRIVATE-OLD-BODY")]),
        wheel(tmp_path / "b.whl", system=3, entries=[("a", b"PRIVATE-NEW-BODY")]),
    )
    assert not report["allowed"] and not report["payload_equal"]
    assert "PRIVATE-" not in json.dumps(report)


def test_payload_manifest_keeps_original_order_and_locates_changed_or_missing_members(tmp_path):
    original = wheel(
        tmp_path / "original.whl",
        entries=[
            ("b", b"PRIVATE-UNCHANGED"),
            ("a", b"PRIVATE-ORIGINAL"),
            ("missing", b"PRIVATE-MISSING"),
        ],
    )
    rebuilt = wheel(
        tmp_path / "rebuilt.whl",
        system=3,
        entries=[
            ("a", b"PRIVATE-CHANGED"),
            ("b", b"PRIVATE-UNCHANGED"),
        ],
    )
    report = compare_wheels(original, rebuilt)
    members = report["payload_members"]
    assert len(members) == report["entry_count"] == 3
    assert [(row["index"], row["entry"], row["equal"]) for row in members] == [
        (0, "b", True),
        (1, "a", False),
        (2, "missing", False),
    ]
    assert (
        members[0]["original_sha256"]
        == members[0]["rebuilt_sha256"]
        == hashlib.sha256(b"PRIVATE-UNCHANGED").hexdigest()
    )
    assert members[1]["original_sha256"] == hashlib.sha256(b"PRIVATE-ORIGINAL").hexdigest()
    assert members[1]["rebuilt_sha256"] == hashlib.sha256(b"PRIVATE-CHANGED").hexdigest()
    assert members[2]["rebuilt_sha256"] is None
    assert not report["allowed"] and "PRIVATE-" not in json.dumps(report)


@pytest.mark.parametrize(
    "change", ["attributes", "comment", "entry_comment", "extra", "trailing", "local_header"]
)
def test_other_metadata_or_archive_bytes_are_rejected_even_with_same_payload(tmp_path, change):
    original = wheel(tmp_path / "original.whl")
    rebuilt = wheel(
        tmp_path / "rebuilt.whl",
        system=3,
        attributes=(0o100600 << 16) if change == "attributes" else 0o100644 << 16,
        comment=b"PRIVATE-ARCHIVE-COMMENT" if change == "comment" else b"",
    )
    if change in {"entry_comment", "extra"}:
        with zipfile.ZipFile(original) as source:
            data = [(info.filename, source.read(info)) for info in source.infolist()]
        with zipfile.ZipFile(rebuilt, "w") as target:
            for name, payload in data:
                info = zipfile.ZipInfo(name, (2020, 1, 2, 3, 4, 6))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                if change == "entry_comment":
                    info.comment = b"PRIVATE-ENTRY-COMMENT"
                else:
                    info.extra = b"\x99\x99\x04\x00data"
                target.writestr(info, payload)
    elif change == "trailing":
        rebuilt.write_bytes(rebuilt.read_bytes() + b"trailing data")
    elif change == "local_header":
        raw = bytearray(rebuilt.read_bytes())
        raw[10] ^= 1  # 本地头的 DOS 时间字节，payload 与中央目录仍不变。
        rebuilt.write_bytes(raw)
    report = compare_wheels(original, rebuilt)
    assert report["payload_equal"] and not report["allowed"]
    assert report["unexpected_archive_difference_count"] > 0
    assert "PRIVATE-" not in json.dumps(report)


def test_unsupported_or_reversed_os_change_is_not_allowed(tmp_path):
    report = compare_wheels(
        wheel(tmp_path / "a.whl", system=3), wheel(tmp_path / "b.whl", system=0)
    )
    assert report["payload_equal"] and not report["allowed"]
    assert all(not row["allowed"] for row in report["metadata_differences"])


def test_missing_member_is_rejected(tmp_path):
    report = compare_wheels(
        wheel(tmp_path / "a.whl"), wheel(tmp_path / "b.whl", entries=[("a", b"x")])
    )
    assert not report["allowed"] and report["entry_count"] != report["rebuilt_entry_count"]


def test_invalid_zip_is_rejected_without_outputting_its_contents(tmp_path):
    bad = tmp_path / "bad.whl"
    bad.write_bytes(b"PRIVATE-NOT-A-ZIP")
    report = compare_wheels(wheel(tmp_path / "a.whl"), bad)
    assert not report["allowed"] and report["error_type"] == "BadZipFile"
    assert "PRIVATE-" not in json.dumps(report)


def test_cli_writes_new_report_without_modifying_or_overwriting_inputs(tmp_path, monkeypatch):
    first, second = wheel(tmp_path / "a.whl"), wheel(tmp_path / "b.whl", system=3)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["compare", "--original", str(first), "--rebuilt", str(second), "--output", str(output)],
    )
    assert main() == 0 and json.loads(output.read_text(encoding="utf-8"))["allowed"]
    with pytest.raises(FileExistsError):
        main()
