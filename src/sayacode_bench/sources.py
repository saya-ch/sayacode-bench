"""固定公开基准的 Git 身份，并从原始 Git blob 构造不受换行配置影响的快照。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    """所有可变分支都在这里收敛为完整提交号。"""

    name: str
    url: str
    revision: str
    tasks_path: str
    license: str
    checksums_path: str | None = None


SOURCES = {
    "swe-bench-pro-v2": SourceSpec(
        name="swe-bench-pro-v2",
        url="https://github.com/scaleapi/SWE-bench_Pro-os.git",
        revision="66f92766bba642462d4bbe5479e83f91f9211862",
        tasks_path="v2/tasks",
        license="MIT",
        checksums_path="v2/SHA256SUMS",
    ),
    "terminal-bench-2.1": SourceSpec(
        name="terminal-bench-2.1",
        url="https://github.com/harbor-framework/terminal-bench-2-1.git",
        revision="7131e4375048a0e408a8fb404b5f499d726b695b",
        tasks_path="tasks",
        license="Apache-2.0",
    ),
}


@dataclass(frozen=True)
class SourceSnapshot:
    spec: SourceSpec
    path: Path
    archive_sha256: str
    checksums_verified: int

    @property
    def tasks_path(self) -> Path:
        return self.path / self.spec.tasks_path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bounded(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in relative:
        raise ValueError(f"不允许的快照路径：{relative}")
    candidate = root.joinpath(*parsed.parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"路径越过快照边界：{relative}")
    return candidate


def verify_checksums(root: Path, manifest: Path) -> int:
    """严格按字节验证上游 SHA256SUMS，不把 CRLF 视作等价内容。"""

    count = 0
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
        if match is None:
            raise ValueError(f"校验清单第 {number} 行格式错误")
        expected, relative = match.groups()
        target = _bounded(root, relative)
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"上游校验文件缺失或为链接：{relative}")
        if sha256_file(target) != expected:
            raise ValueError(f"上游 SHA256 校验失败：{relative}；请使用 Git blob 快照检查换行转换")
        count += 1
    if count == 0:
        raise ValueError("上游校验清单为空")
    return count


def _extract_archive(archive: Path, destination: Path) -> None:
    """不接受归档中的链接或特殊设备，避免下载材料写出缓存边界。"""

    with tarfile.open(archive, "r") as bundle:
        for member in bundle:
            target = _bounded(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError(f"归档文件不可读取：{member.name}")
                with stream, target.open("wb") as output:
                    while block := stream.read(1024 * 1024):
                        output.write(block)
                target.chmod(member.mode & 0o777)
            else:
                raise ValueError(f"归档包含不支持的链接或设备：{member.name}")


def _git(repository: Path, *arguments: str, output: Any = subprocess.PIPE) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=output,
        stderr=subprocess.PIPE,
    )
    return result.stdout or b""


def fetch_source(
    spec: SourceSpec,
    cache: Path,
    *,
    local_repository: Path | None = None,
) -> SourceSnapshot:
    """获取固定提交；本地缓存只提供对象，不信任其磁盘文件和换行设置。"""

    if re.fullmatch(r"[0-9a-f]{40}", spec.revision) is None:
        raise ValueError("源版本必须是完整的 40 位 Git 提交号")
    if re.fullmatch(r"[a-z0-9][a-z0-9.-]*", spec.name) is None:
        raise ValueError("源名称只能包含小写字母、数字、点和连字符")
    if not spec.url.startswith("https://"):
        raise ValueError("公开源必须使用 HTTPS")
    cache = cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{spec.name}-{spec.revision}"
    identity = destination / ".sayacode-source.json"
    if destination.exists():
        saved = json.loads(identity.read_text(encoding="utf-8"))
        if saved["source"] != asdict(spec):
            raise ValueError("缓存源身份与请求不符")
        verified = _verify_source(spec, destination)
        if tree_digest(destination) != saved["tree_sha256"]:
            raise ValueError("缓存快照文件已被修改")
        return SourceSnapshot(spec, destination, saved["archive_sha256"], verified)

    with tempfile.TemporaryDirectory(prefix="source-", dir=cache) as temporary:
        temporary_path = Path(temporary)
        if local_repository is None:
            repository = temporary_path / "git"
            repository.mkdir()
            _git(repository, "init", "--bare")
            _git(repository, "fetch", "--depth=1", spec.url, spec.revision)
        else:
            repository = local_repository.resolve()
        actual = _git(repository, "rev-parse", f"{spec.revision}^{{commit}}").decode().strip()
        if actual != spec.revision:
            raise ValueError("Git 返回的提交身份不符")
        archive = temporary_path / "source.tar"
        with archive.open("wb") as stream:
            _git(repository, "archive", "--format=tar", spec.revision, output=stream)
        staging = temporary_path / "snapshot"
        staging.mkdir()
        _extract_archive(archive, staging)
        verified = _verify_source(spec, staging)
        archive_hash = sha256_file(archive)
        metadata = {
            "schema_version": 1,
            "source": asdict(spec),
            "archive_sha256": archive_hash,
            "tree_sha256": tree_digest(staging),
            "checksums_verified": verified,
            "materialization": "git archive from pinned commit; no checkout filters",
        }
        (staging / identity.name).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staging.rename(destination)
    return SourceSnapshot(spec, destination, archive_hash, verified)


def _verify_source(spec: SourceSpec, root: Path) -> int:
    if not _bounded(root, spec.tasks_path).is_dir():
        raise ValueError("快照缺少任务目录")
    license_path = root / "LICENSE"
    if not license_path.is_file():
        raise ValueError("快照缺少许可证")
    if spec.checksums_path is None:
        return 0
    manifest = _bounded(root, spec.checksums_path)
    return verify_checksums(manifest.parent, manifest)


def tree_digest(root: Path) -> str:
    """项目自己的目录身份；不冒充 Harbor Hub 的规范化任务 digest。"""

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.name == ".sayacode-source.json":
            continue
        if path.is_symlink():
            raise ValueError(f"快照包含链接：{path.relative_to(root)}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode() + b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


@dataclass(frozen=True)
class TaskRecord:
    benchmark: str
    revision: str
    task_id: str
    task_name: str
    repository: str
    language: str
    category: str
    difficulty: str
    leakage_group: str
    instruction_sha256: str
    config_sha256: str
    task_tree_sha256: str
    agent: dict[str, Any]
    verifier: dict[str, Any]
    environment: dict[str, Any]
    has_custom_compose: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


# 语言标签来自公开仓库的主体语言，仅用于抽样分层，不决定模型适配。
_SWE_LANGUAGES = {
    "ansible/ansible": "python",
    "internetarchive/openlibrary": "python",
    "qutebrowser/qutebrowser": "python",
    "flipt-io/flipt": "go",
    "future-architect/vuls": "go",
    "gravitational/teleport": "go",
    "navidrome/navidrome": "go",
    "NodeBB/NodeBB": "javascript",
    "element-hq/element-web": "typescript",
    "protonmail/webclients": "typescript",
    "tutao/tutanota": "typescript",
}


def build_catalog(snapshot: SourceSnapshot) -> list[TaskRecord]:
    """只解析公开配置与标识；参考解、隐藏断言和测试名不参与分层。"""

    records = []
    for config_path in sorted(snapshot.tasks_path.glob("*/task.toml")):
        task = config_path.parent
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        metadata = data.get("metadata", {})
        task_id = task.name
        if snapshot.spec.name == "swe-bench-pro-v2":
            match = re.fullmatch(r"instance_(.+?)-([0-9a-f]{40})(?:-.+)?", task_id)
            if match is None:
                raise ValueError(f"SWE 任务标识格式错误：{task_id}")
            repository = match[1].replace("__", "/")
            language = _SWE_LANGUAGES.get(repository, "unknown")
            leakage_group = f"{repository}:{match[2]}"
        else:
            repository = "terminal-bench"
            tags = [str(tag).lower() for tag in metadata.get("tags", [])]
            language = next(
                (
                    item
                    for item in ("python", "typescript", "javascript", "go", "rust", "cpp", "c")
                    if item in tags
                ),
                "unknown",
            )
            leakage_group = task_id
        records.append(
            TaskRecord(
                benchmark=snapshot.spec.name,
                revision=snapshot.spec.revision,
                task_id=task_id,
                task_name=data.get("task", {}).get("name", task_id),
                repository=repository,
                language=language,
                category=str(metadata.get("category", "unknown")),
                difficulty=str(metadata.get("difficulty", "unknown")),
                leakage_group=leakage_group,
                instruction_sha256=sha256_file(task / "instruction.md"),
                config_sha256=sha256_file(config_path),
                task_tree_sha256=tree_digest(task),
                agent=data.get("agent", {}),
                verifier=data.get("verifier", {}),
                environment=data.get("environment", {}),
                has_custom_compose=any(
                    (task / "environment" / filename).exists()
                    for filename in ("docker-compose.yaml", "docker-compose.yml")
                ),
            )
        )
    if not records:
        raise ValueError("源快照中没有 Harbor 任务")
    return records
