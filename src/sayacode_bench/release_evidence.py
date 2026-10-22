"""指定私有仓库的 Release 工件薄适配；不创建 Release、不提取 tar。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPOSITORY = "saya-ch/sayacode-bench-runs"
MAX_PART_SIZE = 1024**3
_CHUNK = 1024**2
_TIMEOUT = 900
_SHA = re.compile(r"[0-9a-f]{64}\Z")
BILLING_BOUNDARY = (
    "GitHub 当前文档未将 Release assets 列入 Actions artifacts/Packages 存储池；"
    "这不是永久免费保证。本适配器不更改零美元账户预算，Actions 计算分钟仍受限。"
)


class ReleaseEvidenceError(ValueError):
    """只报告固定错误说明，不输出 gh 的 stderr、凭据或原始响应。"""


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _arguments(repository: str, release_id: int, release_tag: str) -> None:
    if (
        repository != REPOSITORY
        or not _positive(release_id)
        or not isinstance(release_tag, str)
        or not release_tag.strip()
        or any(character in release_tag for character in "\r\n\0")
    ):
        raise ReleaseEvidenceError("需要指定私有执行仓库、正整数 Release ID 和固定 tag")


def _json(arguments: list[str]) -> Any:
    try:
        result = subprocess.run(
            ["gh", "api", *arguments, "--hostname", "github.com"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            raise ReleaseEvidenceError("gh API 未成功完成")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ReleaseEvidenceError("gh API 未返回已确认的 JSON 结果") from None


def _guard(repository: str, release_id: int, release_tag: str, repo_id: int | None = None) -> int:
    _arguments(repository, release_id, release_tag)
    project = _json([f"repos/{repository}"])
    release = _json([f"repos/{repository}/releases/{release_id}"])
    if (
        not isinstance(project, dict)
        or project.get("full_name") != repository
        or project.get("private") is not True
        or project.get("visibility") != "private"
        or not _positive(project.get("id"))
        or repo_id is not None
        and project["id"] != repo_id
        or not isinstance(release, dict)
        or type(release.get("id")) is not int
        or release["id"] != release_id
        or release.get("tag_name") != release_tag
        or release.get("draft") is not True
    ):
        raise ReleaseEvidenceError("仓库私有性、身份或固定 draft Release 未确认")
    return int(project["id"])


def _assets(repository: str, release_id: int) -> list[dict[str, Any]]:
    pages = _json(
        [f"repos/{repository}/releases/{release_id}/assets?per_page=100", "--paginate", "--slurp"]
    )
    if (
        not isinstance(pages, list)
        or any(not isinstance(page, list) for page in pages)
        or any(not isinstance(asset, dict) for page in pages for asset in page)
    ):
        raise ReleaseEvidenceError("Release asset 目录未确认")
    assets = [asset for page in pages for asset in page]
    if len(assets) > 1000:
        raise ReleaseEvidenceError("Release asset 数量超过当前官方上限")
    return assets


def _name(archive_sha: str, number: int, count: int, part_sha: str) -> str:
    return f"bundle-{archive_sha}.part-{number:05d}-of-{count:05d}-{part_sha}.bin"


def _asset_matches(asset: Any, part: Mapping[str, Any]) -> bool:
    return (
        isinstance(asset, dict)
        and _positive(asset.get("id"))
        and asset.get("name") == part["name"]
        and asset.get("state") == "uploaded"
        and type(asset.get("size")) is int
        and asset["size"] == part["size"]
        and asset.get("digest") == "sha256:" + part["sha256"]
    )


def _parts(archive: Path, directory: Path, size: int) -> tuple[str, int, list[dict[str, Any]]]:
    if type(size) is not int or not 0 < size <= MAX_PART_SIZE:
        raise ReleaseEvidenceError("分片必须为正整数且不超过 1 GiB")
    if not archive.is_file() or not 0 < archive.stat().st_size <= size * 1000:
        raise ReleaseEvidenceError("需要非空 tar 文件且分片数不超过 1000")
    directory.mkdir(parents=True, exist_ok=False)
    total, digest = 0, hashlib.sha256()
    parts: list[dict[str, Any]] = []
    before = archive.stat()
    with archive.open("rb") as source:
        while True:
            chunk = source.read(min(_CHUNK, size))
            if not chunk:
                break
            number, length, part_digest = len(parts) + 1, 0, hashlib.sha256()
            temporary = directory / f"part-{number:05d}.tmp"
            with temporary.open("xb") as target:
                while chunk:
                    target.write(chunk)
                    digest.update(chunk)
                    part_digest.update(chunk)
                    total += len(chunk)
                    if total > before.st_size:
                        raise ReleaseEvidenceError("拆分期间原 tar 已增长")
                    length += len(chunk)
                    if length == size:
                        break
                    chunk = source.read(min(_CHUNK, size - length))
            parts.append({"number": number, "size": length, "sha256": part_digest.hexdigest()})
    after = archive.stat()
    if before.st_size != total or (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ReleaseEvidenceError("拆分期间原 tar 已变化")
    archive_sha = digest.hexdigest()
    for part in parts:
        part["name"] = _name(archive_sha, part["number"], len(parts), part["sha256"])
        (directory / f"part-{part['number']:05d}.tmp").rename(directory / part["name"])
    return archive_sha, total, parts


def upload_archive(
    archive: Path,
    *,
    repository: str,
    release_id: int,
    release_tag: str,
    work_dir: Path,
    part_size_bytes: int = MAX_PART_SIZE,
) -> dict[str, Any]:
    """固定 draft 中追加 SHA 命名的分片；同字节幂等，不覆盖或删除任何 asset。"""
    _arguments(repository, release_id, release_tag)
    repo_id = _guard(repository, release_id, release_tag)
    archive_sha, total, parts = _parts(archive, work_dir, part_size_bytes)
    existing = _assets(repository, release_id)
    missing = sum(
        not any(asset.get("name") == part["name"] for asset in existing) for part in parts
    )
    if len(existing) + missing > 1000:
        raise ReleaseEvidenceError("分片将超过单 Release 的 1000 asset 上限")
    ids = set()
    for part in parts:
        _guard(repository, release_id, release_tag, repo_id)
        matches = [asset for asset in existing if asset.get("name") == part["name"]]
        if len(matches) > 1:
            raise ReleaseEvidenceError("同名 asset 不唯一")
        if matches:
            asset = matches[0]
        else:
            asset = _json(
                [
                    f"https://uploads.github.com/repos/{repository}/releases/{release_id}/assets?name={part['name']}",
                    "--method",
                    "POST",
                    "--header",
                    "Content-Type: application/octet-stream",
                    "--input",
                    str(work_dir / part["name"]),
                ]
            )
        if not _asset_matches(asset, part) or asset["id"] in ids:
            raise ReleaseEvidenceError("asset ID、名称、大小或服务端 digest 与本地分片冲突")
        current = _json([f"repos/{repository}/releases/assets/{asset['id']}"])
        if not _asset_matches(current, part) or current["id"] != asset["id"]:
            raise ReleaseEvidenceError("上传或复用后的 asset 事实未确认")
        ids.add(asset["id"])
        part.update(asset_id=asset["id"], service_digest=asset["digest"])
    _guard(repository, release_id, release_tag, repo_id)
    manifest = {
        "schema_version": 1,
        "repository": repository,
        "repository_id": repo_id,
        "release_id": release_id,
        "release_tag": release_tag,
        "release_draft_required": True,
        "archive_sha256": archive_sha,
        "archive_size": total,
        "part_size_bytes": part_size_bytes,
        "parts": parts,
        "billing_boundary": BILLING_BOUNDARY,
        "guaranteed_free_forever": False,
        "account_budget_changed": False,
        "actions_compute_minutes_still_apply": True,
    }
    with (work_dir / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def _manifest(value: Mapping[str, Any], repository: str, release_id: int, release_tag: str) -> None:
    _arguments(repository, release_id, release_tag)
    parts = value.get("parts")
    size = value.get("part_size_bytes")
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("repository") != repository
        or not _positive(value.get("repository_id"))
        or type(value.get("release_id")) is not int
        or value["release_id"] != release_id
        or value.get("release_tag") != release_tag
        or value.get("release_draft_required") is not True
        or not isinstance(value.get("archive_sha256"), str)
        or not _SHA.fullmatch(value["archive_sha256"])
        or not _positive(value.get("archive_size"))
        or type(size) is not int
        or not 0 < size <= MAX_PART_SIZE
        or not isinstance(parts, list)
        or not 0 < len(parts) <= 1000
    ):
        raise ReleaseEvidenceError("完整 tar manifest 身份或分片范围无效")
    ids = set()
    total = 0
    for number, part in enumerate(parts, 1):
        if (
            not isinstance(part, dict)
            or type(part.get("number")) is not int
            or part["number"] != number
            or not _positive(part.get("asset_id"))
            or part["asset_id"] in ids
            or not isinstance(part.get("sha256"), str)
            or not _SHA.fullmatch(part["sha256"])
            or not _positive(part.get("size"))
            or part["size"] > size
            or number != len(parts)
            and part["size"] != size
            or part.get("name")
            != _name(value["archive_sha256"], number, len(parts), part["sha256"])
            or part.get("service_digest") != "sha256:" + part["sha256"]
        ):
            raise ReleaseEvidenceError("分片顺序、ID、名称、大小或 digest 无效")
        ids.add(part["asset_id"])
        total += part["size"]
    if total != value["archive_size"]:
        raise ReleaseEvidenceError("分片大小之和与完整 tar 不一致")


def download_archive(
    manifest: Mapping[str, Any],
    *,
    repository: str,
    release_id: int,
    release_tag: str,
    output_dir: Path,
) -> Path:
    """下载到独占目录、流式拼接并核验完整 tar；提取仍交给原 restore_archive。"""
    _manifest(manifest, repository, release_id, release_tag)
    _guard(repository, release_id, release_tag, manifest["repository_id"])
    assets = _assets(repository, release_id)
    output_dir.mkdir(parents=True, exist_ok=False)
    temporary = output_dir / "bundle.tar.gz.partial"
    archive_digest = hashlib.sha256()
    with temporary.open("xb") as archive:
        for part in manifest["parts"]:
            _guard(repository, release_id, release_tag, manifest["repository_id"])
            listed = [asset for asset in assets if asset.get("id") == part["asset_id"]]
            if len(listed) != 1 or not _asset_matches(listed[0], part):
                raise ReleaseEvidenceError("分片不属于固定 Release 或其目录事实已变化")
            endpoint = f"repos/{repository}/releases/assets/{part['asset_id']}"
            current = _json([endpoint])
            if not _asset_matches(current, part) or current["id"] != part["asset_id"]:
                raise ReleaseEvidenceError("下载前 asset 身份或服务端 digest 已变化")
            path = output_dir / part["name"]
            try:
                with path.open("xb") as target:
                    result = subprocess.run(
                        [
                            "gh",
                            "api",
                            endpoint,
                            "--hostname",
                            "github.com",
                            "--header",
                            "Accept: application/octet-stream",
                        ],
                        stdout=target,
                        stderr=subprocess.PIPE,
                        check=False,
                        timeout=_TIMEOUT,
                    )
                if result.returncode != 0:
                    raise ReleaseEvidenceError("gh 未确认分片下载完成")
            except (OSError, subprocess.SubprocessError):
                raise ReleaseEvidenceError("gh 分片下载未完成") from None
            if path.stat().st_size != part["size"]:
                raise ReleaseEvidenceError("分片下载大小不匹配")
            part_digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(_CHUNK):
                    part_digest.update(chunk)
                    archive_digest.update(chunk)
                    archive.write(chunk)
            if part_digest.hexdigest() != part["sha256"]:
                raise ReleaseEvidenceError("分片下载 SHA256 不匹配")
    if (
        temporary.stat().st_size != manifest["archive_size"]
        or archive_digest.hexdigest() != manifest["archive_sha256"]
    ):
        raise ReleaseEvidenceError("拼接后的完整 tar SHA256 或大小不匹配")
    _guard(repository, release_id, release_tag, manifest["repository_id"])
    final = output_dir / "bundle.tar.gz"
    temporary.rename(final)
    return final
