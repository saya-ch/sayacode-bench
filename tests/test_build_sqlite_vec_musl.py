"""离线行为检查；不启动 Docker，不编译或加载原生库，不调用模型。"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import wheel
import yaml
from wheel.wheelfile import WheelFile

from scripts import build_sqlite_vec_musl as builder

TEMPLATE = Path(__file__).resolve().parents[1] / ".github/workflows/build-platform-runtime.yml"


@pytest.fixture
def packaging(tmp_path: Path) -> tuple[Path, Path, Path]:
    inputs, output = tmp_path / "inputs", tmp_path / "output"
    inputs.mkdir()
    output.mkdir()
    # 压缩的原始三平台 Tag 与真实 sqlite-dist wheel 的形式相同。
    with WheelFile(inputs / builder.OLD_WHEEL, "w") as archive:
        archive.writestr("sqlite_vec/__init__.py", b'__version__ = "0.1.9"\n')
        archive.writestr("sqlite_vec/vec0.so", b"original-glibc-fixture")
        archive.writestr(
            f"{builder.DIST}/METADATA", b"Metadata-Version: 2.1\nName: sqlite-vec\nVersion: 0.1.9\n"
        )
        archive.writestr(f"{builder.DIST}/top_level.txt", b"sqlite_vec\n")
        archive.writestr(
            f"{builder.DIST}/WHEEL",
            b"Wheel-Version: 1.0\nGenerator: sqlite-dist 0.0.1-alpha.22\nRoot-Is-Purelib: false\nTag: py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux1_x86_64\n",
        )
    native = output / "vec0.so"
    native.write_bytes(b"different-musl-fixture-not-an-actual-library")
    assert wheel.__version__ == "0.45.1"
    return inputs, output, native


def test_real_standard_wheel_pack_preserves_python_and_record(packaging: Any) -> None:
    inputs, output, native = packaging
    derived = builder.package(inputs, output, native)
    report = builder.validate_wheel(inputs / builder.OLD_WHEEL, derived)
    assert report["record_verified"] and report["native_binary_changed"]
    assert report["original_native_sha256"] != report["native_sha256"]
    assert not (output / "native-result.json").exists()
    assert not (output / "provenance.json").exists()
    with zipfile.ZipFile(derived) as archive:
        assert all(row.date_time == (1980, 1, 1, 0, 0, 0) for row in archive.infolist())
    assert json.loads((output / "wheel-pack.json").read_bytes())["returncode"] == 0


@pytest.mark.parametrize(
    "member", builder.PRESERVED + [f"{builder.DIST}/WHEEL", "sqlite_vec/vec0.so"]
)
def test_rejects_changed_metadata_wrong_platform_or_unchanged_binary(
    packaging: Any, member: str
) -> None:
    inputs, output, native = packaging
    derived = builder.package(inputs, output, native)
    with zipfile.ZipFile(derived) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    payloads[member] = b"wrong"
    if member == "sqlite_vec/vec0.so":
        payloads[member] = b"original-glibc-fixture"
    with zipfile.ZipFile(derived, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError):
        builder.validate_wheel(inputs / builder.OLD_WHEEL, derived)


def test_record_tampering_is_rejected(packaging: Any) -> None:
    inputs, output, native = packaging
    derived = builder.package(inputs, output, native)
    with zipfile.ZipFile(derived) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    payloads[f"{builder.DIST}/RECORD"] = b"sqlite_vec/vec0.so,sha256=wrong,1\n"
    with zipfile.ZipFile(derived, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="RECORD"):
        builder.validate_wheel(inputs / builder.OLD_WHEEL, derived)


def test_prepare_checks_actual_download_hash_without_overwrite(
    tmp_path: Path, monkeypatch: Any
) -> None:
    payload = b"fixed input"
    digest = builder.hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(builder, "INPUTS", {"test.bin": ("https://example.invalid/test", digest)})
    monkeypatch.setattr(builder.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    output = tmp_path / "new"
    builder.prepare(output)
    assert builder.check_inputs(output)["test.bin"]["sha256"] == digest
    with pytest.raises(FileExistsError):
        builder.prepare(output)
    (output / "test.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA"):
        builder.check_inputs(output)


def test_prepare_preserves_bad_download_without_success_receipt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(builder, "INPUTS", {"test.bin": ("https://example.invalid/test", "0" * 64)})
    monkeypatch.setattr(builder.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad"))
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="SHA"):
        builder.prepare(output)
    assert (output / "test.bin").read_bytes() == b"bad"
    assert not (output / "inputs.json").exists()
    assert json.loads((output / "prepare-failure.json").read_bytes())["passed"] is False


def test_source_licenses_and_headers_exact_only(tmp_path: Path) -> None:
    inputs, output = tmp_path / "inputs", tmp_path / "out"
    inputs.mkdir()
    output.mkdir()
    for archive_name, files in {
        "amalgamation.tar.gz": {
            "sqlite-vec.c": b"code",
            "sqlite-vec.h": f'"v0.1.9" {builder.COMMIT}'.encode(),
            "../escape": b"ignored",
        },
        "sqlite-vec-v0.1.9-source.tar.gz": {
            "sqlite-vec-0.1.9/LICENSE-MIT": b"mit",
            "sqlite-vec-0.1.9/LICENSE-APACHE": b"apache",
        },
    }.items():
        with tarfile.open(inputs / archive_name, "w:gz") as archive:
            for name, value in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
    with zipfile.ZipFile(inputs / "sqlite-amalgamation-3450300.zip", "w") as archive:
        for name in ("sqlite3.h", "sqlite3ext.h"):
            archive.writestr("sqlite-amalgamation-3450300/" + name, b"public domain header")
    builder.source_files(inputs, output)
    assert (output / "licenses/LICENSE-MIT").read_bytes() == b"mit"
    assert (output / "sqlite3ext.h").read_bytes() == b"public domain header"
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "dynamic,versions,symbols",
    [
        ("Shared library: [libc.so.6]", "GLIBC_2.2.5", "sqlite3_vec_init"),
        ("Shared library: [libc.musl-x86_64.so.1]", "GLIBC_2.14", "sqlite3_vec_init"),
        ("Shared library: [libc.musl-x86_64.so.1]", "", "missing_entry"),
        (
            "Shared library: [libc.musl-x86_64.so.1]\nShared library: [other.so]",
            "",
            "sqlite3_vec_init",
        ),
    ],
)
def test_abi_gate_rejects_wrong_libc_symbols_or_extra_dependencies(
    dynamic: str, versions: str, symbols: str
) -> None:
    with pytest.raises(ValueError):
        builder.check_abi(dynamic, versions, symbols)


def test_abi_gate_accepts_musl_only() -> None:
    builder.check_abi(
        "Shared library: [libc.musl-x86_64.so.1]", "No version information", "sqlite3_vec_init"
    )


def test_worker_rejects_glibc_before_any_pack_or_load(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(builder, "check_inputs", lambda p: {})
    monkeypatch.setattr(builder.platform, "system", lambda: "Linux")
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    calls = []

    def fake(arguments: list[str], directory: Path, label: str, **kw: Any) -> bytes:
        calls.append(label)
        return {
            "readelf-dynamic": b"Shared library: [libc.so.6]",
            "readelf-versions": b"GLIBC_2.14",
            "readelf-symbols": b"sqlite3_vec_init",
        }.get(label, b"")

    monkeypatch.setattr(builder, "command", fake)
    with pytest.raises(ValueError, match="GLIBC"):
        builder.worker(tmp_path / "inputs", tmp_path)
    assert "compile" in calls and "install-derived" not in calls
    assert not (tmp_path / "native-result.json").exists()


def test_docker_offline_readonly_sources_same_absolute_paths(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GH_TOKEN", "must-not-forward")
    arguments = builder.docker_arguments(
        tmp_path / "inputs", tmp_path / "output", "test-name", "test-token", "1001:1002"
    )
    assert arguments[arguments.index("--network") + 1] == "none"
    assert "--read-only" in arguments
    assert builder.IMAGE in arguments and "latest" not in " ".join(arguments)
    assert "GH_TOKEN" not in " ".join(arguments) and "must-not-forward" not in arguments
    assert any("/source,readonly" in value for value in arguments)
    assert arguments[-1] == (tmp_path / "output").resolve().as_posix()
    assert f"SOURCE_DATE_EPOCH={builder.SOURCE_DATE_EPOCH}" in arguments
    assert arguments[1] == "create" and "--rm" not in arguments
    assert arguments[arguments.index("--name") + 1] == "test-name"
    assert f"{builder.OWNER_LABEL}=test-token" in arguments
    assert arguments[arguments.index("--user") + 1] == "1001:1002"
    assert arguments[arguments.index("--cap-drop") + 1] == "ALL"


def test_nonzero_command_keeps_stdout_stderr_and_exit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="命令失败"):
        builder.command(
            [
                sys.executable,
                "-c",
                "import sys; print('out'); print('err',file=sys.stderr); sys.exit(7)",
            ],
            tmp_path,
            "bad",
        )
    assert (tmp_path / "bad.stdout").read_bytes().strip() == b"out"
    assert (tmp_path / "bad.stderr").read_bytes().strip() == b"err"
    assert json.loads((tmp_path / "bad.json").read_bytes())["returncode"] == 7


def test_command_timeout_keeps_original_output_and_timeout_fact(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        builder.command(
            [
                sys.executable,
                "-c",
                "import sys,time; print('before-timeout',flush=True); print('partial-error',file=sys.stderr,flush=True); time.sleep(30)",
            ],
            tmp_path,
            "timeout",
            timeout=1,
        )
    assert (tmp_path / "timeout.stdout").read_bytes().strip() == b"before-timeout"
    assert (tmp_path / "timeout.stderr").read_bytes().strip() == b"partial-error"
    receipt = json.loads((tmp_path / "timeout.json").read_bytes())
    assert receipt["timed_out"] is True and receipt["timeout_seconds"] == 1
    assert receipt["returncode"] is None


@pytest.fixture
def fake_docker(monkeypatch: Any) -> dict[str, Any]:
    """只模拟 Docker 客户端应答；实际 command 仍写所有原始日志。"""
    state: dict[str, Any] = {"mode": "start-timeout", "present": False, "calls": [], "id": "a" * 64}
    other = {"ID": "b" * 64, "Names": "unrelated-container"}

    def fake(
        arguments: list[str],
        *,
        stdout: Any,
        stderr: Any,
        check: bool,
        timeout: float,
        **kwargs: Any,
    ) -> Any:
        assert arguments[0] == "docker" and timeout > 0 and check is False
        state["calls"].append((list(arguments), timeout))
        response: Any = None
        if arguments[1] == "create":
            state["name"] = arguments[arguments.index("--name") + 1]
            state["token"] = arguments[arguments.index("--label") + 1].split("=", 1)[1]
            state["user"] = arguments[arguments.index("--user") + 1]
            state["present"] = state["mode"] != "create-unknown-absent"
            if state["mode"] in {"create-timeout", "create-unknown-absent"}:
                stderr.write(b"create transport interrupted\n")
                raise subprocess.TimeoutExpired(arguments, timeout)
            Path(arguments[arguments.index("--cidfile") + 1]).write_text(state["id"])
            stdout.write((state["id"] + "\n").encode())
        elif arguments[1:3] == ["container", "inspect"]:
            assert arguments[-1] == state["id"]
            token = state["token"]
            if state["mode"] == "changed-owner" and state.get("started"):
                token = "unrelated-owner"
            response = [
                {
                    "Id": state["id"],
                    "Name": "/" + state["name"],
                    "Image": builder.IMAGE_ID,
                    "Config": {
                        "Labels": {builder.OWNER_LABEL: token},
                        "User": "mismatched-user"
                        if state["mode"] == "wrong-user"
                        else state["user"],
                    },
                }
            ]
        elif arguments[1:3] == ["start", "--attach"]:
            assert arguments[-1] == state["id"]
            state["started"] = True
            stdout.write(b"original compile output\n")
            stderr.write(b"original native stderr\n")
            if state["mode"] not in {"success", "success-remove-still-present"}:
                raise subprocess.TimeoutExpired(arguments, timeout)
        elif arguments[1:3] == ["container", "ls"]:
            if state["mode"] == "list-error":
                stderr.write(b"No such container")
                return SimpleNamespace(returncode=1)
            rows = [other]
            if state["present"]:
                rows.append({"ID": state["id"], "Names": state["name"]})
            stdout.write(b"\n".join(json.dumps(row).encode() for row in rows))
        elif arguments[1:4] == ["container", "rm", "--force"]:
            assert arguments[-1] == state["id"]  # 绝不触碰 other。
            if state["mode"] in {"remove-still-present", "success-remove-still-present"}:
                return SimpleNamespace(returncode=1)
            state["present"] = False
            if state["mode"] == "remove-timeout-gone":
                raise subprocess.TimeoutExpired(arguments, timeout)
        else:
            raise AssertionError(arguments)
        if response is not None:
            stdout.write(json.dumps(response).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(builder.subprocess, "run", fake)
    return state


@pytest.mark.parametrize("mode", ["start-timeout", "create-timeout", "remove-timeout-gone"])
def test_native_timeout_confirms_owned_container_removed_and_keeps_logs(
    tmp_path: Path, fake_docker: Any, mode: str
) -> None:
    fake_docker["mode"] = mode
    with pytest.raises(subprocess.TimeoutExpired):
        builder.native_container(tmp_path / "inputs", tmp_path)
    cleanup = json.loads((tmp_path / "container-cleanup.json").read_bytes())
    assert cleanup["confirmed_gone"] is True and cleanup["confirmed_not_running"] is True
    assert cleanup["container_id"] == "a" * 64
    removes = [args for args, timeout in fake_docker["calls"] if args[1:3] == ["container", "rm"]]
    assert removes == [["docker", "container", "rm", "--force", "a" * 64]]
    builder.require_archive_safe(tmp_path)
    if mode != "create-timeout":
        assert (
            tmp_path / "offline-native-build.stdout"
        ).read_bytes() == b"original compile output\n"
        assert (
            tmp_path / "offline-native-build.stderr"
        ).read_bytes() == b"original native stderr\n"
        assert (
            json.loads((tmp_path / "offline-native-build.json").read_bytes())["timed_out"] is True
        )
        assert any(args[1] == "start" and timeout == 600 for args, timeout in fake_docker["calls"])
    else:
        assert not any(args[1] == "start" for args, timeout in fake_docker["calls"])


def test_success_also_removes_only_confirmed_owner(tmp_path: Path, fake_docker: Any) -> None:
    fake_docker["mode"] = "success"
    report = builder.native_container(tmp_path / "inputs", tmp_path)
    assert report["confirmed_gone"] is True and report["start_requested"] is True
    assert not fake_docker["present"]
    identity = tmp_path.stat()
    assert report["user"] == fake_docker["user"] == f"{identity.st_uid}:{identity.st_gid}"
    builder.require_archive_safe(tmp_path)


def test_actual_container_user_mismatch_stops_before_start(
    tmp_path: Path, fake_docker: Any
) -> None:
    fake_docker["mode"] = "wrong-user"
    with pytest.raises(ValueError, match="身份不符"):
        builder.native_container(tmp_path / "inputs", tmp_path)
    assert not any(args[1] == "start" for args, timeout in fake_docker["calls"])
    assert not any(args[1:3] == ["container", "rm"] for args, timeout in fake_docker["calls"])


@pytest.mark.parametrize("mismatch", [None, "uid", "gid", "owner", "missing"])
def test_native_smoke_user_must_equal_request_and_actual_output_owner(
    tmp_path: Path, mismatch: str | None
) -> None:
    identity = tmp_path.stat()
    uid, gid = identity.st_uid, identity.st_gid
    builder.write(
        tmp_path / "container-owner.json",
        {"user": f"{uid + 1 if mismatch == 'owner' else uid}:{gid}"},
    )
    result = {
        "effective_uid": uid + 1 if mismatch == "uid" else uid,
        "effective_gid": gid + 1 if mismatch == "gid" else gid,
    }
    if mismatch == "missing":
        result.pop("effective_uid")
    if mismatch is None:
        builder.check_smoke_user(result, tmp_path)
    else:
        with pytest.raises(ValueError, match="UID/GID"):
            builder.check_smoke_user(result, tmp_path)


def test_successful_native_is_not_signed_if_cleanup_unconfirmed(
    tmp_path: Path, fake_docker: Any
) -> None:
    fake_docker["mode"] = "success-remove-still-present"
    with pytest.raises(ValueError, match="清理未确认"):
        builder.native_container(tmp_path / "inputs", tmp_path)
    with pytest.raises(ValueError, match="未确认"):
        builder.require_archive_safe(tmp_path)
    assert not (tmp_path / "provenance.json").exists()


@pytest.mark.parametrize("mode", ["changed-owner", "remove-still-present", "list-error"])
def test_cleanup_uncertainty_blocks_archive_without_repeating_removal(
    tmp_path: Path, fake_docker: Any, mode: str
) -> None:
    fake_docker["mode"] = mode
    with pytest.raises(subprocess.TimeoutExpired):
        builder.native_container(tmp_path / "inputs", tmp_path)
    cleanup = json.loads((tmp_path / "container-cleanup.json").read_bytes())
    assert cleanup["safe_to_archive"] is False
    with pytest.raises(ValueError, match="未确认"):
        builder.require_archive_safe(tmp_path)
    removes = [args for args, timeout in fake_docker["calls"] if args[1:3] == ["container", "rm"]]
    assert len(removes) == (1 if mode == "remove-still-present" else 0)
    assert (tmp_path / "offline-native-build.stdout").read_bytes() == b"original compile output\n"


def test_unknown_create_never_started_is_not_falsely_marked_gone(
    tmp_path: Path, fake_docker: Any
) -> None:
    fake_docker["mode"] = "create-unknown-absent"
    with pytest.raises(subprocess.TimeoutExpired):
        builder.native_container(tmp_path / "inputs", tmp_path)
    report = json.loads((tmp_path / "container-cleanup.json").read_bytes())
    assert report["start_requested"] is False and report["late_create_possible"] is True
    assert report["confirmed_gone"] is False and report["confirmed_not_running"] is True
    assert not any(args[1] == "start" for args, timeout in fake_docker["calls"])
    builder.require_archive_safe(tmp_path)


def test_image_identity_failure_stops_before_native_and_records_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(builder.platform, "system", lambda: "Linux")
    monkeypatch.setattr(builder, "check_inputs", lambda p: {})
    monkeypatch.setattr(builder, "source_files", lambda a, b: None)
    calls = []

    def fake(arguments: list[str], directory: Path, label: str, **kw: Any) -> bytes:
        calls.append(label)
        return (
            b'[{"Id":"wrong","Os":"linux","Architecture":"amd64"}]'
            if label == "image-inspect"
            else b""
        )

    monkeypatch.setattr(builder, "command", fake)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="身份"):
        builder.build(tmp_path / "inputs", output, "a" * 40)
    assert calls == ["image-pull", "image-inspect"]
    assert json.loads((output / "build-failure.json").read_bytes())["passed"] is False
    assert not (output / "provenance.json").exists()


def workflow() -> dict[str, Any]:
    return dict(yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))


def inline(step_name: str) -> str:
    step = next(row for row in workflow()["jobs"]["build"]["steps"] if row.get("name") == step_name)
    match = re.search(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", step["run"], re.S)
    assert match
    return match[1]


@pytest.mark.parametrize(
    "override",
    [{}, {"GITHUB_RUN_ATTEMPT": "2"}, {"SOURCE_SHA": "main"}, {"private": False}, {"id": 123}],
)
def test_workflow_admission_executes(
    tmp_path: Path, monkeypatch: Any, override: dict[str, Any]
) -> None:
    handoff = tmp_path / "build-handoff"
    handoff.mkdir()
    project = {"id": 1429748203, "private": True, "full_name": "saya-ch/sayacode-bench-runs"}
    project.update({key: value for key, value in override.items() if key in project})
    (handoff / "repository.json").write_text(json.dumps(project))
    environment = {
        "RUNNER_TEMP": str(tmp_path),
        "BUILD_ROOT": str(tmp_path / "bundle/runtime-support/sqlite-vec-musl-v1"),
        "SOURCE_SHA": "a" * 40,
        "GITHUB_SHA": "b" * 40,
        "GITHUB_RUN_ID": "1",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    environment.update({key: value for key, value in override.items() if key in environment})
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    code = compile(inline("核实私有仓库与唯一尝试"), str(TEMPLATE), "exec")
    if override:
        with pytest.raises(AssertionError):
            exec(code, {})
        assert not Path(environment["BUILD_ROOT"]).exists()
    else:
        exec(code, {})
        assert Path(environment["BUILD_ROOT"], "host/workflow.json").is_file()


def test_workflow_has_no_supplier_secrets_and_bounded_failure_retention() -> None:
    value = workflow()
    raw = TEMPLATE.read_text(encoding="utf-8")
    assert "secrets." not in raw
    assert value["jobs"]["build"]["runs-on"] == "ubuntu-24.04"
    assert "acknowledge_free_actions" in value["jobs"]["build"]["if"]
    steps = value["jobs"]["build"]["steps"]
    native = next(row for row in steps if row.get("id") == "native")
    assert "env" not in native
    assert "preflight_installation_storage reserve" in raw
    archive = next(row for row in steps if row.get("id") == "archive")
    assert "always()" in archive["if"] and "'failure'" in archive["if"]
    assert "upload_archive" in archive["run"] and "root.relative_to(bundle)" in archive["run"]
    fallback = next(row for row in steps if row.get("id") == "fallback")
    assert "preflight_installation_storage fallback" in fallback["run"]
    assert fallback["run"].index("preflight_installation_storage fallback") < fallback["run"].index(
        "cp "
    )
    assert "cmp .github/workflows/build-platform-runtime.yml" in raw
    assert "persist-credentials: false" in raw
    assert 'prepare_cloud_runner.py --output "$RUNNER_TEMP/' in raw


def test_archive_failure_keeps_raw_tar_and_explicit_unconfirmed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sayacode_bench import release_evidence

    bundle = tmp_path / "bundle"
    root = bundle / "runtime-support/sqlite-vec-musl-v1"
    (root / "host").mkdir(parents=True)
    (root / "host/native-attempt.txt").write_text("123\n")
    (root / "failed-native.log").write_bytes(b"original failure")
    (tmp_path / "build-handoff").mkdir()
    for key, value in {
        "BUILD_ROOT": str(root),
        "BUNDLE_ROOT": str(bundle),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ID": "123",
        "SOURCE_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)

    def uncertain(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("unknown upload outcome")

    monkeypatch.setattr(release_evidence, "upload_archive", uncertain)
    with pytest.raises(RuntimeError, match="unknown"):
        exec(compile(inline("保存成功或失败的完整构建原件"), str(TEMPLATE), "exec"), {})
    archive_path = tmp_path / "sqlite-vec-musl-runtime.tar.gz"
    with tarfile.open(archive_path) as archive:
        stream = archive.extractfile("runtime-support/sqlite-vec-musl-v1/failed-native.log")
        assert stream is not None and stream.read() == b"original failure"
    receipt = json.loads((tmp_path / "build-handoff/release-unconfirmed.json").read_bytes())
    assert receipt["retention_unconfirmed"] is True and receipt["automatic_retry"] is False
    assert not (tmp_path / "build-handoff/runtime-archive-manifest.json").exists()


def test_workflow_does_not_archive_while_native_writer_may_live(
    tmp_path: Path, monkeypatch: Any
) -> None:
    bundle = tmp_path / "bundle"
    root = bundle / "runtime-support/sqlite-vec-musl-v1"
    (root / "host").mkdir(parents=True)
    (root / "host/native-attempt.txt").write_text("123\n")
    (root / "output").mkdir()
    (root / "output/container-owner.json").write_text(
        json.dumps({"name": "owned", "token": "token"})
    )
    (root / "output/container-cleanup.json").write_text(
        json.dumps(
            {
                "name": "owned",
                "token": "token",
                "safe_to_archive": False,
                "confirmed_not_running": False,
            }
        )
    )
    (tmp_path / "build-handoff").mkdir()
    for key, value in {
        "BUILD_ROOT": str(root),
        "BUNDLE_ROOT": str(bundle),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_RUN_ID": "123",
        "SOURCE_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="未确认"):
        exec(compile(inline("保存成功或失败的完整构建原件"), str(TEMPLATE), "exec"), {})
    assert not (tmp_path / "sqlite-vec-musl-runtime.tar.gz").exists()
    report = json.loads(
        (tmp_path / "build-handoff/container-retention-unconfirmed.json").read_bytes()
    )
    assert report["retention_unconfirmed"] is True and report["archive_created"] is False
