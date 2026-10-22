"""只读比较 wheel；仅容许中央目录 made-by OS 从 Windows 0 变为 Unix 3。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

_METADATA = (
    "filename",
    "orig_filename",
    "date_time",
    "compress_type",
    "comment",
    "extra",
    "create_system",
    "create_version",
    "extract_version",
    "reserved",
    "flag_bits",
    "volume",
    "internal_attr",
    "external_attr",
    "header_offset",
    "CRC",
    "compress_size",
    "file_size",
)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": _hash(value)}
    return list(value) if isinstance(value, tuple) else value


def _central_os_offsets(archive: zipfile.ZipFile, data: bytes) -> list[int]:
    """按已解析目录逐条核实 46 字节头及变长字段，不搜索任意签名字节。"""
    position = archive.start_dir
    result = []
    for info in archive.infolist():
        if (
            position < 0
            or position + 46 > len(data)
            or data[position : position + 4] != b"PK\x01\x02"
        ):
            raise ValueError("invalid_central_directory")
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", data, position + 28)
        end = position + 46 + name_size + extra_size + comment_size
        if end > len(data):
            raise ValueError("truncated_central_directory")
        name = data[position + 46 : position + 46 + name_size]
        encoding = "utf-8" if info.flag_bits & 0x800 else "cp437"
        if name.decode(encoding) != info.orig_filename or data[position + 5] != info.create_system:
            raise ValueError("central_directory_identity_mismatch")
        result.append(position + 5)
        position = end
    return result


def _payloads(archive: zipfile.ZipFile) -> dict[tuple[str, int], str]:
    """流式核对实际解压内容；重复名称仍按出现次数保留，不输出正文。"""
    occurrences: Counter[str] = Counter()
    result = {}
    for info in archive.infolist():
        occurrences[info.filename] += 1
        digest = hashlib.sha256()
        with archive.open(info) as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        result[info.filename, occurrences[info.filename]] = digest.hexdigest()
    return result


def compare_wheels(original: Path, rebuilt: Path) -> dict[str, Any]:
    """名称、顺序、payload、元数据和全部非豁免字节必须一致；不修改输入。"""
    left, right = original.read_bytes(), rebuilt.read_bytes()
    different = [index for index, values in enumerate(zip(left, right)) if values[0] != values[1]]
    report: dict[str, Any] = {
        "allowed": False,
        "original_sha256": _hash(left),
        "rebuilt_sha256": _hash(right),
        "entry_count": None,
        "rebuilt_entry_count": None,
        "names_equal": False,
        "order_equal": False,
        "payload_equal": False,
        "payload_members": [],
        "metadata_differences": [],
        "archive_byte_difference_count": len(different) + abs(len(left) - len(right)),
        "archive_size_equal": len(left) == len(right),
        "allowed_create_system_difference_count": 0,
        "unexpected_archive_difference_count": None,
        "scope": "仅比较调用方提供的 wheel 文件；执行宿主由调用方另行记录；不改写输入。",
    }
    try:
        with (
            zipfile.ZipFile(io.BytesIO(left)) as first,
            zipfile.ZipFile(io.BytesIO(right)) as second,
        ):
            original_entries, rebuilt_entries = first.infolist(), second.infolist()
            names = [info.filename for info in original_entries]
            rebuilt_names = [info.filename for info in rebuilt_entries]
            original_payloads, rebuilt_payloads = _payloads(first), _payloads(second)
            report.update(
                entry_count=len(names),
                rebuilt_entry_count=len(rebuilt_names),
                names_equal=sorted(names) == sorted(rebuilt_names),
                order_equal=names == rebuilt_names,
                payload_equal=original_payloads == rebuilt_payloads,
                payload_members=[
                    {
                        "entry": key[0],
                        "index": index,
                        "original_sha256": digest,
                        "rebuilt_sha256": rebuilt_payloads.get(key),
                        "equal": digest == rebuilt_payloads.get(key),
                    }
                    for index, (key, digest) in enumerate(original_payloads.items())
                ],
            )
            offsets = _central_os_offsets(first, left)
            rebuilt_offsets = _central_os_offsets(second, right)
            permitted = set()
            metadata_valid = len(original_entries) == len(rebuilt_entries)
            for index, (before, after) in enumerate(zip(original_entries, rebuilt_entries)):
                for field in _METADATA:
                    a, b = getattr(before, field), getattr(after, field)
                    if a == b:
                        continue
                    accepted = field == "create_system" and (a, b) == (0, 3)
                    report["metadata_differences"].append(
                        {
                            "index": index,
                            "entry": before.filename,
                            "field": field,
                            "original": _safe(a),
                            "rebuilt": _safe(b),
                            "allowed": accepted,
                        }
                    )
                    metadata_valid = metadata_valid and accepted
                    if accepted and offsets[index] == rebuilt_offsets[index]:
                        permitted.add(offsets[index])
            unexpected = sum(index not in permitted for index in different) + abs(
                len(left) - len(right)
            )
            report.update(
                allowed_create_system_difference_count=sum(
                    index in permitted for index in different
                ),
                unexpected_archive_difference_count=unexpected,
                allowed=bool(
                    report["order_equal"]
                    and report["payload_equal"]
                    and metadata_valid
                    and offsets == rebuilt_offsets
                    and unexpected == 0
                ),
            )
    except (
        OSError,
        ValueError,
        UnicodeError,
        RuntimeError,
        zipfile.BadZipFile,
        NotImplementedError,
    ) as exc:
        report["error_type"] = type(exc).__name__
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rebuilt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_wheels(args.original, args.rebuilt)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as target:
            target.write(encoded)
    else:
        print(encoded, end="")
    return 0 if report["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
