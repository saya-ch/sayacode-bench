"""仅为 sqlite-vec 0.1.9 生成有来源记录的 musl 派生 wheel；不改 SUT 或研究输入。"""

from __future__ import annotations

import argparse
import base64
import csv
import email.policy
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import uuid
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path
from typing import Any

IMAGE = "quay.io/pypa/musllinux_1_2_x86_64@sha256:773cb7e73652e4596eba6a9d593b01278f86772641d6530a6660422d30e50f36"
IMAGE_ID = "sha256:9f87c2804a55ad1e663dfe815f52b4e9f410384e898a396899e3a0d33a8efc8d"
COMMIT = "e9f598abfa0c06b328d8fe5da9c3760cce74be10"
OLD_WHEEL = (
    "sqlite_vec-0.1.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux1_x86_64.whl"
)
NEW_WHEEL = "sqlite_vec-0.1.9-1sayacodemusl-py3-none-musllinux_1_2_x86_64.whl"
TOOL_WHEEL = "wheel-0.45.1-py3-none-any.whl"
SOURCE_DATE_EPOCH = "315532800"
COMMAND_TIMEOUT_SECONDS = 120
PULL_TIMEOUT_SECONDS = 600
NATIVE_TIMEOUT_SECONDS = 600
OWNER_LABEL = "org.sayacode-bench.sqlite-vec-build"
DIST = "sqlite_vec-0.1.9.dist-info"
PRESERVED = ["sqlite_vec/__init__.py", f"{DIST}/METADATA", f"{DIST}/top_level.txt"]
INPUTS = {
    "sqlite-vec-v0.1.9-source.tar.gz": (
        "https://codeload.github.com/asg017/sqlite-vec/tar.gz/refs/tags/v0.1.9",
        "9823e737d9934dcbe85dff75d3fca81018a9beee803d70fa77b16faab5d61dc9",
    ),
    "amalgamation.tar.gz": (
        "https://github.com/asg017/sqlite-vec/releases/download/v0.1.9/sqlite-vec-0.1.9-amalgamation.tar.gz",
        "3acd67cb4aff080c7050926fd3cf8227905fe5b7ee3829d8ee5024ab1283cf61",
    ),
    "sqlite-amalgamation-3450300.zip": (
        "https://www.sqlite.org/2024/sqlite-amalgamation-3450300.zip",
        "ea170e73e447703e8359308ca2e4366a3ae0c4304a8665896f068c736781c651",
    ),
    OLD_WHEEL: (
        "https://files.pythonhosted.org/packages/6f/ad/6afd073b0f817b3e03f9e37ad626ae341805891f23c74b5292818f49ac63/"
        + OLD_WHEEL,
        "1515727990b49e79bcaf75fdee2ffc7d461f8b66905013231251f1c8938e7786",
    ),
    TOOL_WHEEL: (
        "https://files.pythonhosted.org/packages/0b/2c/87f3254fd8ffd29e4c02732eee68a83a1d3c346ae39bc6822dcbcb697f2b/"
        + TOOL_WHEEL,
        "708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248",
    ),
}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha(path), "size_in_bytes": path.stat().st_size}


def write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_inputs(directory: Path) -> dict[str, Any]:
    result = {}
    for name, (url, expected) in INPUTS.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink(), f"缺少固定原件：{name}")
        require(sha(path) == expected, f"固定原件 SHA 不符：{name}")
        result[name] = {**reference(path), "url": url}
    return result


def prepare(directory: Path) -> None:
    """网络只用于取得固定公开原件；不隐式重试或覆盖。"""
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for name, (url, expected) in INPUTS.items():
            with urllib.request.urlopen(url, timeout=120) as response:
                with (directory / name).open("xb") as stream:
                    shutil.copyfileobj(response, stream)
            require(sha(directory / name) == expected, f"下载 SHA 不符：{name}")
        write(directory / "inputs.json", check_inputs(directory))
    except Exception as error:
        write(
            directory / "prepare-failure.json",
            {
                "passed": False,
                "error_type": type(error).__name__,
                "reason": str(error),
                "model_calls": 0,
                "automatic_retry": False,
            },
        )
        raise


def command(
    arguments: list[str],
    directory: Path,
    label: str,
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> bytes:
    """每个命令独立保存参数、退出码与原始输出，失败也保留。"""
    try:
        with (directory / f"{label}.stdout").open("xb") as stdout:
            with (directory / f"{label}.stderr").open("xb") as stderr:
                result = subprocess.run(
                    arguments, stdout=stdout, stderr=stderr, check=False, timeout=timeout, **kwargs
                )
    except (OSError, subprocess.SubprocessError) as error:
        write(
            directory / f"{label}.json",
            {
                "argv": arguments,
                "returncode": None,
                "timeout_seconds": timeout,
                "timed_out": isinstance(error, subprocess.TimeoutExpired),
                "error_type": type(error).__name__,
                "reason": str(error),
            },
        )
        raise
    write(
        directory / f"{label}.json",
        {
            "argv": arguments,
            "returncode": result.returncode,
            "timeout_seconds": timeout,
            "timed_out": False,
        },
    )
    require(result.returncode == 0, f"命令失败：{label}；请核原始 stdout/stderr")
    return (directory / f"{label}.stdout").read_bytes()


def source_files(inputs: Path, output: Path) -> None:
    """只按固定名称取出源文件和许可证，不解压任意路径。"""
    with tarfile.open(inputs / "amalgamation.tar.gz") as archive:
        for name in ("sqlite-vec.c", "sqlite-vec.h"):
            member = archive.getmember(name)
            require(member.isfile(), "amalgamation 成员必须是普通文件")
            stream = archive.extractfile(member)
            assert stream is not None
            (output / name).write_bytes(stream.read())
    header = (output / "sqlite-vec.h").read_text()
    require(COMMIT in header and '"v0.1.9"' in header, "amalgamation 版本或源码身份不符")
    with zipfile.ZipFile(inputs / "sqlite-amalgamation-3450300.zip") as archive:
        for name in ("sqlite3.h", "sqlite3ext.h"):
            (output / name).write_bytes(archive.read(f"sqlite-amalgamation-3450300/{name}"))
    licenses = output / "licenses"
    licenses.mkdir()
    with tarfile.open(inputs / "sqlite-vec-v0.1.9-source.tar.gz") as archive:
        for name in ("LICENSE-MIT", "LICENSE-APACHE"):
            stream = archive.extractfile(f"sqlite-vec-0.1.9/{name}")
            assert stream is not None
            (licenses / name).write_bytes(stream.read())
    # SQLite 的 public-domain blessing 随原 sqlite3.h / sqlite3ext.h 原字节保留。


def validate_wheel(original: Path, derived: Path) -> dict[str, Any]:
    require(derived.name == NEW_WHEEL, "派生 wheel 文件名不符")
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(derived) as new:
        require(len(new.namelist()) == len(set(new.namelist())), "wheel 有重复成员")
        require(set(new.namelist()) == set(old.namelist()), "wheel 成员集合改变")
        for name in PRESERVED:
            require(old.read(name) == new.read(name), f"原 Python/metadata 字节改变：{name}")
        require(
            old.read("sqlite_vec/vec0.so") != new.read("sqlite_vec/vec0.so"),
            "未替换原 glibc 二进制",
        )
        metadata = new.read(f"{DIST}/WHEEL").decode()
        require(
            re.findall(r"^Tag: (.+)$", metadata, re.M) == ["py3-none-musllinux_1_2_x86_64"],
            "平台 Tag 不符",
        )
        require("Build: 1sayacodemusl\n" in metadata, "缺少显式派生 build tag")
        require("Root-Is-Purelib: false" in metadata, "原生 wheel 错标为纯 Python")
        records = list(csv.reader(io.StringIO(new.read(f"{DIST}/RECORD").decode())))
        require(len(records) == len(new.namelist()), "RECORD 未覆盖完整 wheel")
        require({row[0] for row in records} == set(new.namelist()), "RECORD 成员重复或遗漏")
        for name, digest, size in records:
            if name == f"{DIST}/RECORD":
                require(digest == size == "", "RECORD 自身字段无效")
                continue
            payload = new.read(name)
            expected = (
                base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
            )
            require(
                digest == "sha256=" + expected and size == str(len(payload)), f"RECORD 不符：{name}"
            )
        return {
            "preserved_members": PRESERVED,
            "record_verified": True,
            "native_binary_changed": True,
            "original_native_sha256": hashlib.sha256(old.read("sqlite_vec/vec0.so")).hexdigest(),
            "native_sha256": hashlib.sha256(new.read("sqlite_vec/vec0.so")).hexdigest(),
        }


def package(inputs: Path, output: Path, native: Path) -> Path:
    """官方 unpack/pack 负责 ZIP/RECORD；仅明确修改派生 WHEEL 标签。"""
    environment = dict(
        os.environ, PYTHONPATH=str(inputs / TOOL_WHEEL), SOURCE_DATE_EPOCH=SOURCE_DATE_EPOCH
    )
    wheel = [sys.executable, "-m", "wheel"]
    command(
        wheel + ["unpack", str(inputs / OLD_WHEEL), "--dest", str(output / "unpacked")],
        output,
        "wheel-unpack",
        env=environment,
    )
    unpacked = output / "unpacked/sqlite_vec-0.1.9"
    shutil.copyfile(native, unpacked / "sqlite_vec/vec0.so")
    wheel_metadata = unpacked / DIST / "WHEEL"
    info = BytesParser(policy=email.policy.compat32).parsebytes(wheel_metadata.read_bytes())
    del info["Tag"], info["Generator"]
    info["Tag"] = "py3-none-musllinux_1_2_x86_64"
    info["Generator"] = "sayacode-bench derived-musl; wheel 0.45.1"
    wheel_metadata.write_bytes(info.as_bytes())
    command(
        wheel
        + ["pack", str(unpacked), "--dest-dir", str(output), "--build-number", "1sayacodemusl"],
        output,
        "wheel-pack",
        env=environment,
    )
    derived = output / NEW_WHEEL
    validate_wheel(inputs / OLD_WHEEL, derived)
    return derived


SMOKE = r"""
import ctypes, json, os, platform, shutil, sqlite3, subprocess, sys
import sqlite_vec

assert sqlite_vec.__version__ == "0.1.9"
module_path = os.path.abspath(sqlite_vec.__file__)
module_dir = os.path.dirname(module_path)
so_path = os.path.join(module_dir, "vec0.so")

# musl 镜像内的 CPython（cp310-cp314）其 sqlite3 模块均未编译 loadable extension，
# 无法用 enable_load_extension 加载扩展。改用 ctypes 校验入口符号，再以镜像自带
# 的 sqlite3 CLI 做真实 SQL 加载与向量运算，两者都必须通过。
lib = ctypes.CDLL(so_path)
assert hasattr(lib, "sqlite3_vec_init"), "扩展缺少 sqlite3_vec_init 入口"
cli = shutil.which("sqlite3")
assert cli, "镜像内缺少 sqlite3 CLI"
statements = "\n".join([
    ".load " + os.path.join(module_dir, "vec0"),
    "SELECT vec_version();",
    "SELECT vec_distance_L2('[1,2,3]', '[4,6,3]');",
    "CREATE VIRTUAL TABLE items USING vec0(embedding float[3]);",
    "INSERT INTO items(rowid, embedding) VALUES (1, '[1,2,3]'), (2, '[4,6,3]');",
    "SELECT rowid || '|' || distance FROM items WHERE embedding MATCH '[1,2,3]' AND k=1;",
    "DELETE FROM items WHERE rowid=2;",
    "SELECT count(*) FROM items;",
]) + "\n"
completed = subprocess.run([cli, ":memory:"], input=statements, capture_output=True, text=True, timeout=120)
assert completed.returncode == 0, "sqlite3 CLI 执行失败：" + completed.stderr
rows = [line for line in completed.stdout.splitlines() if line.strip()]
assert len(rows) == 4, "sqlite3 输出行数不符：" + repr(rows)
version, distance_text, nearest_text, count_text = rows
assert version == "v0.1.9", version
distance = float(distance_text)
assert abs(distance - 5.0) < 1e-9, distance
assert nearest_text == "1|0.0", nearest_text
count = int(count_text)
assert count == 1, count

print(json.dumps({"builder_python": sys.version, "builder_executable": sys.executable,
 "effective_uid": os.geteuid(), "effective_gid": os.getegid(),
 "sqlite_version": sqlite3.sqlite_version, "module_path": module_path,
 "machine": platform.machine(), "vec_version": version, "distance_l2": distance,
 "nearest": [1, 0.0], "insert_query_delete_passed": True, "sut_python_verified": False,
 "extension_load_method": "ctypes+sqlite3-cli",
 "python_has_enable_load_extension": hasattr(sqlite3.connect(":memory:"), "enable_load_extension")}))
"""


def check_abi(dynamic: str, versions: str, symbols: str) -> None:
    require("GLIBC_" not in dynamic + versions + symbols, "原生库包含 GLIBC 版本依赖")
    require("libc.so.6" not in dynamic, "原生库依赖 glibc libc.so.6")
    dependencies = re.findall(r"Shared library: \[(.+?)\]", dynamic)
    require(dependencies == ["libc.musl-x86_64.so.1"], "原生库不是预期的仅 musl 依赖")
    require("sqlite3_vec_init" in symbols, "缺少 SQLite 扩展入口")


def output_user(output: Path) -> str:
    identity = output.stat()
    return f"{identity.st_uid}:{identity.st_gid}"


def check_smoke_user(result: dict[str, Any], output: Path) -> None:
    owner = json.loads((output / "container-owner.json").read_bytes())
    uid, gid = result.get("effective_uid"), result.get("effective_gid")
    require(type(uid) is int and type(gid) is int, "原生 smoke 缺少实际有效 UID/GID")
    require(
        f"{uid}:{gid}" == owner["user"] == output_user(output),
        "原生 smoke 的实际 UID/GID 与输出属主或容器请求不符",
    )


def worker(inputs: Path, output: Path) -> None:
    check_inputs(inputs)
    require(
        platform.system() == "Linux" and platform.machine() == "x86_64",
        "builder 必须为 Linux x86_64",
    )
    command(["gcc", "--version"], output, "gcc-version")
    command(["readelf", "--version"], output, "readelf-version")
    command([sys.executable, "-VV"], output, "builder-python-version")
    native = output / "vec0.so"
    source = output / "source"
    command(
        [
            "gcc",
            "-fPIC",
            "-shared",
            "-Wall",
            "-Wextra",
            "-I" + str(source),
            "-O3",
            "-march=x86-64",
            "-mtune=generic",
            # musl 不提供 u_int*_t 这组 BSD/glibc 别名，而原 amalgamation 在
            # 非 Windows/Emscripten/Cosmopolitan/wasi 分支里依赖它们。这里只在
            # 编译期补上别名，不改动源文件字节，保持对官方原件的可追溯性。
            "-Du_int8_t=uint8_t",
            "-Du_int16_t=uint16_t",
            "-Du_int32_t=uint32_t",
            "-Du_int64_t=uint64_t",
            str(source / "sqlite-vec.c"),
            "-o",
            str(native),
            "-lm",
        ],
        output,
        "compile",
        timeout=240,
    )
    dynamic = command(["readelf", "-d", str(native)], output, "readelf-dynamic").decode()
    versions = command(
        ["readelf", "--version-info", str(native)], output, "readelf-versions"
    ).decode()
    symbols = command(
        ["readelf", "--dyn-syms", "--wide", str(native)], output, "readelf-symbols"
    ).decode()
    check_abi(dynamic, versions, symbols)
    derived = package(inputs, output, native)
    require(
        validate_wheel(inputs / OLD_WHEEL, derived)["native_sha256"] == sha(native),
        "最终 wheel 与实际编译 ELF 不同",
    )
    # 验证最终 wheel 中的实际二进制，不使用编译目录里的偶然模块。
    installed = output / "smoke-site"
    command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            "--target",
            str(installed),
            str(derived),
        ],
        output,
        "install-derived",
        env=dict(os.environ, PIP_CONFIG_FILE=os.devnull),
    )
    smoke = command(
        [sys.executable, "-c", SMOKE],
        output,
        "sqlite-smoke",
        env=dict(os.environ, PYTHONPATH=str(installed)),
    )
    result = json.loads(smoke)
    check_smoke_user(result, output)
    require(result["module_path"].startswith(str(installed) + "/"), "加载模块不来自最终 wheel")
    write(
        output / "native-result.json",
        {
            "passed": True,
            "abi": "musllinux_1_2_x86_64",
            "wheel": reference(derived),
            "compiled_native": reference(native),
            "abi_evidence": {
                "dynamic": reference(output / "readelf-dynamic.stdout"),
                "versions": reference(output / "readelf-versions.stdout"),
                "symbols": reference(output / "readelf-symbols.stdout"),
            },
            "checks": result,
            "model_calls": 0,
            "sut_tested": False,
        },
    )


def docker_arguments(inputs: Path, output: Path, name: str, token: str, user: str) -> list[str]:
    # 相同绝对路径映射，运行证据可原字节并入同一 BUNDLE。
    native_inputs, native_output = inputs.resolve().as_posix(), output.resolve().as_posix()
    require(bool(re.fullmatch(r"[0-9]+:[0-9]+", user)), "builder 必须显式指定数值 UID:GID")
    return [
        "docker",
        "create",
        "--user",
        user,
        "--name",
        name,
        "--label",
        f"{OWNER_LABEL}={token}",
        "--cidfile",
        str(output / "container.cid"),
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,size=512m",
        "--mount",
        f"type=bind,src={inputs.resolve()},dst={native_inputs},readonly",
        "--mount",
        f"type=bind,src={output.resolve()},dst={native_output}",
        "--mount",
        f"type=bind,src={(output / 'source').resolve()},dst={native_output}/source,readonly",
        "--mount",
        f"type=bind,src={(output / 'source/build_sqlite_vec_musl.py').resolve()},dst=/build.py,readonly",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "HOME=/tmp",
        "--env",
        f"SOURCE_DATE_EPOCH={SOURCE_DATE_EPOCH}",
        "--entrypoint",
        "/opt/python/cp313-cp313/bin/python",
        IMAGE,
        "/build.py",
        "worker",
        "--inputs",
        native_inputs,
        "--output",
        native_output,
    ]


def container_list(output: Path, label: str) -> list[dict[str, Any]]:
    raw = command(
        ["docker", "container", "ls", "--all", "--no-trunc", "--format", "{{json .}}"],
        output,
        label,
        timeout=30,
    )
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    require(
        all(
            isinstance(row, dict)
            and re.fullmatch(r"[0-9a-f]{64}", row.get("ID", ""))
            and isinstance(row.get("Names"), str)
            for row in rows
        ),
        "容器列表身份字段无效",
    )
    require(len({row["ID"] for row in rows}) == len(rows), "容器列表 ID 重复")
    return rows


def inspect_owned(output: Path, container_id: str, owner: dict[str, str], label: str) -> None:
    values = json.loads(
        command(
            ["docker", "container", "inspect", container_id],
            output,
            label,
            timeout=30,
        )
    )
    require(isinstance(values, list) and len(values) == 1, "builder 容器身份不唯一")
    value = values[0]
    require(
        value["Id"] == container_id
        and value["Name"] == "/" + owner["name"]
        and value["Image"] == IMAGE_ID
        and value["Config"]["User"] == owner["user"]
        and value["Config"]["Labels"].get(OWNER_LABEL) == owner["token"],
        "builder 容器身份不符，禁止清理",
    )


def cleanup_container(
    output: Path,
    owner: dict[str, str],
    container_id: str | None,
    start_requested: bool,
) -> dict[str, Any]:
    """只移除重新核对过的唯一容器；不按 CLI 错误文本推断容器消失。"""
    report: dict[str, Any] = {
        "schema_version": 1,
        **owner,
        "container_id": container_id,
        "start_requested": start_requested,
        "confirmed_not_running": False,
        "confirmed_gone": False,
        "safe_to_archive": False,
        "removal_requested": False,
    }
    try:
        rows = container_list(output, "cleanup-list-before")
        matches = [
            row
            for row in rows
            if row["Names"] == owner["name"]
            or (container_id is not None and row["ID"] == container_id)
        ]
        require(len(matches) <= 1, "builder 名称与 ID 对应多个容器")
        if not matches:
            # 未收到 create ID 时，迟到的 create 仍可能存在；从未请求 start 不会运行写文件。
            report.update(
                confirmed_not_running=True,
                safe_to_archive=True,
                confirmed_gone=container_id is not None,
                late_create_possible=container_id is None,
            )
            require(not start_requested or container_id is not None, "启动请求缺少已确认 ID")
        else:
            found = matches[0]["ID"]
            require(container_id is None or found == container_id, "builder 名称被另一 ID 占用")
            inspect_owned(output, found, owner, "cleanup-inspect")
            report.update(container_id=found, removal_requested=True)
            try:
                command(
                    ["docker", "container", "rm", "--force", found],
                    output,
                    "cleanup-remove",
                    timeout=30,
                )
            except Exception as error:
                # DELETE 类操作不重发；用下一次只读完整列表确认实际结果。
                report["removal_error"] = {"error_type": type(error).__name__, "reason": str(error)}
            after = container_list(output, "cleanup-list-after")
            require(
                not any(row["ID"] == found or row["Names"] == owner["name"] for row in after),
                "builder 容器仍存在，不能确认停止",
            )
            report.update(confirmed_not_running=True, confirmed_gone=True, safe_to_archive=True)
    except Exception as error:
        report.update(
            safe_to_archive=False,
            confirmed_not_running=False,
            error_type=type(error).__name__,
            reason=str(error),
        )
    write(output / "container-cleanup.json", report)
    return report


def native_container(inputs: Path, output: Path) -> dict[str, Any]:
    token = uuid.uuid4().hex
    owner = {
        "name": "sqlite-vec-musl-" + token,
        "token": token,
        "image": IMAGE,
        "user": output_user(output),
    }
    write(output / "container-owner.json", owner)
    container_id: str | None = None
    start_requested = False
    try:
        created = (
            command(
                docker_arguments(inputs, output, owner["name"], token, owner["user"]),
                output,
                "container-create",
                timeout=60,
            )
            .decode()
            .strip()
        )
        require(bool(re.fullmatch(r"[0-9a-f]{64}", created)), "create 未返回完整容器 ID")
        require((output / "container.cid").read_text().strip() == created, "cidfile 与 create 不同")
        container_id = created
        inspect_owned(output, container_id, owner, "container-inspect-before-start")
        write(output / "container-start-request.json", {**owner, "container_id": container_id})
        start_requested = True
        command(
            ["docker", "start", "--attach", container_id],
            output,
            "offline-native-build",
            timeout=NATIVE_TIMEOUT_SECONDS,
        )
    finally:
        cleanup = cleanup_container(output, owner, container_id, start_requested)
    require(cleanup["confirmed_gone"] is True, "builder 清理未确认，不能签发通过 provenance")
    return cleanup


def require_archive_safe(output: Path) -> None:
    if not (output / "container-owner.json").exists():
        return  # 失败发生于创建容器之前；不存在原生写入进程。
    owner = json.loads((output / "container-owner.json").read_bytes())
    cleanup = json.loads((output / "container-cleanup.json").read_bytes())
    require(
        cleanup.get("name") == owner["name"]
        and cleanup.get("token") == owner["token"]
        and cleanup.get("confirmed_not_running") is True
        and cleanup.get("safe_to_archive") is True,
        "未确认 builder 已停止写入；完整原件保全未确认",
    )


def build(inputs: Path, output: Path, source_sha: str) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "必须提供冻结公开 source SHA")
    require(platform.system() == "Linux", "原生构建只在固定 Linux workflow 执行")
    original = check_inputs(inputs)
    require(not output.resolve().is_relative_to(inputs.resolve()), "输出不能覆盖只读输入")
    output.mkdir(parents=True, exist_ok=False)
    try:
        (output / "source").mkdir()
        source_files(inputs, output / "source")
        shutil.copyfile(Path(__file__), output / "source/build_sqlite_vec_musl.py")
        command(["docker", "pull", IMAGE], output, "image-pull", timeout=PULL_TIMEOUT_SECONDS)
        inspected = json.loads(
            command(["docker", "image", "inspect", IMAGE], output, "image-inspect", timeout=30)
        )
        require(len(inspected) == 1, "builder image 不唯一")
        identity = inspected[0]
        require(
            identity["Id"] == IMAGE_ID
            and identity["Os"] == "linux"
            and identity["Architecture"] == "amd64",
            "builder image 身份不符",
        )
        require(IMAGE in identity["RepoDigests"], "builder RepoDigest 不符")
        native_container(inputs, output)
        result = json.loads((output / "native-result.json").read_bytes())
        require(
            result["passed"] is True and result["wheel"]["sha256"] == sha(output / NEW_WHEEL),
            "原生结果或 wheel SHA 不符",
        )
        wheel = validate_wheel(inputs / OLD_WHEEL, output / NEW_WHEEL)
        write(
            output / "provenance.json",
            {
                "schema_version": 1,
                "passed": True,
                "derived": True,
                "recompiled_native": True,
                "source_sha": source_sha,
                "built_at_utc": datetime.now(UTC).isoformat(),
                "source_date_epoch": int(SOURCE_DATE_EPOCH),
                "source_date_epoch_meaning": "固定 ZIP 最小时间，不是源码提交时间",
                "byte_identical_rebuild_verified": False,
                "upstream_version": "0.1.9",
                "upstream_commit": COMMIT,
                "image": IMAGE,
                "image_id": IMAGE_ID,
                "builder_python_is_sut_python": False,
                "sut_python_verified": False,
                "model_calls": 0,
                "inputs": original,
                "implementation": reference(output / "source/build_sqlite_vec_musl.py"),
                "wheel": reference(output / NEW_WHEEL),
                "wheel_validation": wheel,
                "native_result": reference(output / "native-result.json"),
                "container_cleanup": reference(output / "container-cleanup.json"),
                "evidence": [reference(p) for p in sorted(output.rglob("*")) if p.is_file()],
                "scope": "仅验证此 musl 扩展；不代表固定 SUT 或 46 镜像已通过安装预检",
            },
        )
    except Exception as error:
        write(
            output / "build-failure.json",
            {
                "passed": False,
                "error_type": type(error).__name__,
                "reason": str(error),
                "model_calls": 0,
            },
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "build", "worker"):
        item = commands.add_parser(name)
        item.add_argument("--output", type=Path, required=True)
        if name != "prepare":
            item.add_argument("--inputs", type=Path, required=True)
        if name == "build":
            item.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
    elif args.command == "build":
        build(args.inputs, args.output, args.source_sha)
    else:
        worker(args.inputs, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
