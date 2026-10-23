"""安装信任链分支与实际 Agent 用户硬门禁。"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest

from sayacode_bench.installation import prepare_uv_installer, verify_installed_runtime


class Environment:
    default_user = "agent"

    def __init__(self, codes: tuple[int, ...] = (0,)) -> None:
        self.codes = iter(codes)
        self.commands: list[tuple[str, Any]] = []

    async def exec(self, command: str, **kwargs: Any) -> SimpleNamespace:
        self.commands.append((command, kwargs.get("user")))
        code, stdout, stderr = 0, "", ""
        if command.startswith("curl "):
            code = next(self.codes)
            stderr = "完整TLS诊断\n" if code else ""
        elif "sha256sum" in command:
            stdout = "a" * 64 + "  /installed-agent/sayacode/install-uv.sh\n"
        elif command == "id -u":
            stdout = "1001\n"
        elif "sayacode --version" in command:
            stdout = "SAYACODE 3.2.4\n"
        elif " -c " in command:
            stdout = "SAYACODE_IMPORT_OK\n"
        elif "worker.py --help" in command:
            stdout = "usage: worker.py --profile PROFILE --variant VARIANT --instruction INPUT\n"
        return SimpleNamespace(return_code=code, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize("codes", [(0,), (60, 0), (77, 0)])
async def test_tls_probe_only_repairs_certificate_errors_once(
    tmp_path: Path, codes: tuple[int, ...]
) -> None:
    environment = Environment(codes)
    requested: list[tuple[str, ...]] = []

    async def dependencies(env: Any, names: tuple[str, ...]) -> None:
        assert env is environment
        requested.append(names)

    evidence = tmp_path / "installation"
    report = await prepare_uv_installer(
        environment,
        PurePosixPath("/installed-agent/sayacode/install-uv.sh"),
        evidence,
        dependencies,
    )
    assert report["passed"] is True
    assert requested == ([("curl",)] if codes == (0,) else [("curl",), ("ca_certificates",)])
    downloads = [c for c, _ in environment.commands if c.startswith("curl ")]
    assert len(downloads) == len(codes)
    assert all(c.startswith("curl -q ") and "--proto '=https'" in c for c in downloads)
    assert all("--proto-redir '=https'" in c and "--insecure" not in c for c in downloads)
    assert all("https://astral.sh/uv/0.12.5/install.sh" in c for c in downloads)
    if len(codes) == 2:
        assert (evidence / "download-1.stderr.txt").read_text(encoding="utf-8") == "完整TLS诊断\n"
        assert (
            json.loads((evidence / "download-1.result.json").read_text(encoding="utf-8"))[
                "return_code"
            ]
            == codes[0]
        )


@pytest.mark.parametrize("code", [6, 22, 28, 35, 56, 127])
async def test_other_download_failures_do_not_upgrade_ca(tmp_path: Path, code: int) -> None:
    requested: list[tuple[str, ...]] = []

    async def dependencies(env: Any, names: tuple[str, ...]) -> None:
        requested.append(names)

    evidence = tmp_path / "installation"
    with pytest.raises(RuntimeError, match=f"curl exit={code}"):
        await prepare_uv_installer(
            Environment((code,)), PurePosixPath("/installed-agent/uv.sh"), evidence, dependencies
        )
    assert requested == [("curl",)]
    state = json.loads((evidence / "bootstrap.json").read_text(encoding="utf-8"))
    assert state["passed"] is False and state["ca_repair_attempted"] is False


async def test_repeated_certificate_failure_is_preserved_and_stops(tmp_path: Path) -> None:
    requested: list[tuple[str, ...]] = []

    async def dependencies(env: Any, names: tuple[str, ...]) -> None:
        requested.append(names)

    evidence = tmp_path / "installation"
    with pytest.raises(RuntimeError, match="curl exit=60"):
        await prepare_uv_installer(
            Environment((60, 60)), PurePosixPath("/installed-agent/uv.sh"), evidence, dependencies
        )
    assert requested == [("curl",), ("ca_certificates",)]
    assert (evidence / "download-2.stderr.txt").exists()
    assert json.loads((evidence / "bootstrap.json").read_text(encoding="utf-8"))["passed"] is False


async def test_official_ca_install_failure_is_not_swallowed(tmp_path: Path) -> None:
    async def dependencies(env: Any, names: tuple[str, ...]) -> None:
        if names == ("ca_certificates",):
            raise RuntimeError("APT exit=100")

    evidence = tmp_path / "installation"
    with pytest.raises(RuntimeError, match="APT exit=100"):
        await prepare_uv_installer(
            Environment((77,)), PurePosixPath("/installed-agent/uv.sh"), evidence, dependencies
        )
    state = json.loads((evidence / "bootstrap.json").read_text(encoding="utf-8"))
    assert state["phase"] == "ensure_ca" and state["passed"] is False
    assert not (evidence / "download-2.attempt.json").exists()


async def test_exec_exception_is_not_treated_as_certificate_failure(tmp_path: Path) -> None:
    class Timeout(Environment):
        async def exec(self, command: str, **kwargs: Any) -> SimpleNamespace:
            if command.startswith("curl "):
                raise TimeoutError("native timeout")
            return await super().exec(command, **kwargs)

    requested: list[tuple[str, ...]] = []

    async def dependencies(env: Any, names: tuple[str, ...]) -> None:
        requested.append(names)

    evidence = tmp_path / "installation"
    with pytest.raises(TimeoutError):
        await prepare_uv_installer(
            Timeout(), PurePosixPath("/installed-agent/uv.sh"), evidence, dependencies
        )
    assert requested == [("curl",)]
    result = json.loads((evidence / "download-1.result.json").read_text(encoding="utf-8"))
    assert result["return_code"] is None and result["error_type"] == "TimeoutError"


@pytest.mark.parametrize("broken", [None, "version", "imports", "worker-help"])
async def test_runtime_checks_use_actual_agent_user_and_fail_closed(
    tmp_path: Path, broken: str | None
) -> None:
    class Checked(Environment):
        async def exec(self, command: str, **kwargs: Any) -> SimpleNamespace:
            result = await super().exec(command, **kwargs)
            if (
                broken == "version"
                and "sayacode --version" in command
                or broken == "imports"
                and " -c " in command
                or broken == "worker-help"
                and "worker.py --help" in command
            ):
                result.return_code = 1
            return result

    wheel, requirements = tmp_path / "product.whl", tmp_path / "requirements.txt"
    wheel.write_bytes(b"original-wheel")
    requirements.write_bytes(b"original-requirements")
    environment = Checked()
    if broken:
        with pytest.raises(RuntimeError, match=broken):
            await verify_installed_runtime(
                environment,
                PurePosixPath("/installed-agent/sayacode"),
                tmp_path,
                {"passed": True, "tls_verification_required": True},
                wheel=wheel,
                requirements=requirements,
            )
    else:
        result = await verify_installed_runtime(
            environment,
            PurePosixPath("/installed-agent/sayacode"),
            tmp_path,
            {"passed": True, "tls_verification_required": True},
            wheel=wheel,
            requirements=requirements,
        )
        assert result["passed"] is True and result["agent_effective_uid"] == 1001
        assert result["configured_agent_user"] == "agent"
    assert all(user is None for _, user in environment.commands)
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["passed"] is (broken is None)
    assert receipt["model_execution_performed"] is False
