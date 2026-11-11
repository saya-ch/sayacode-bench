"""musl 镜像适配 + install 失败证据保留的测试（证据见 C:\\sb\\tmp\\audit\\musl\\MUSL.md）。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from scripts import locked_agents as la


class FakeResult:
    def __init__(self, return_code: int = 0, stdout: str = "", stderr: str | None = None) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr


class FakeEnvironment:
    """只实现 install 用到的 exec / upload_file。"""

    def __init__(
        self, *, musl: bool, rc: int = 0, stdout: str = "", stderr: str | None = None
    ) -> None:
        self.musl = musl
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.uploaded: list[Path] = []

    async def exec(
        self, command: str, user: str | None = None, timeout_sec: int | None = None
    ) -> FakeResult:
        if command.startswith("test -f /etc/alpine-release"):
            return FakeResult(0 if self.musl else 1)
        return FakeResult(self.rc, self.stdout, self.stderr)

    async def upload_file(self, path: object, destination: str) -> None:
        self.uploaded.append(Path(str(path)))


def make_agent(cls: type) -> la.LockedClaudeCode:
    agent = object.__new__(cls)
    agent.logger = logging.getLogger("test-musl")
    return agent


def test_install_failure_keeps_rc_and_stdout_when_stderr_none() -> None:
    exc = la._install_failure(
        "claude-code",
        FakeResult(127, "bash: /usr/local/bin/claude: cannot execute: required file not found"),
    )
    text = str(exc)
    assert "rc=127" in text
    assert "cannot execute: required file not found" in text
    assert "stderr=''" in text


async def test_select_tarball_uses_musl_on_musl_image(tmp_path: Path) -> None:
    glibc = tmp_path / "glibc.tgz"
    musl = tmp_path / "musl.tgz"
    glibc.write_bytes(b"g")
    musl.write_bytes(b"m")

    chosen = await la._select_tarball(
        FakeEnvironment(musl=True), glibc=glibc, musl=musl, label="Claude Code"
    )

    assert chosen == musl


async def test_select_tarball_keeps_glibc_on_glibc_image(tmp_path: Path) -> None:
    glibc = tmp_path / "glibc.tgz"
    musl = tmp_path / "musl.tgz"
    glibc.write_bytes(b"g")
    musl.write_bytes(b"m")

    chosen = await la._select_tarball(
        FakeEnvironment(musl=False), glibc=glibc, musl=musl, label="Claude Code"
    )

    assert chosen == glibc


async def test_select_tarball_errors_when_musl_tarball_missing(tmp_path: Path) -> None:
    glibc = tmp_path / "glibc.tgz"
    glibc.write_bytes(b"g")

    with pytest.raises(RuntimeError, match="musl"):
        await la._select_tarball(
            FakeEnvironment(musl=True),
            glibc=glibc,
            musl=tmp_path / "missing.tgz",
            label="Claude Code",
        )


async def test_claude_install_uploads_musl_tarball_on_musl_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    glibc = tmp_path / "claude.tgz"
    musl = tmp_path / "claude-musl.tgz"
    glibc.write_bytes(b"g")
    musl.write_bytes(b"m")
    monkeypatch.setattr(la, "_CLAUDE_TARBALL", glibc)
    monkeypatch.setattr(la, "_CLAUDE_MUSL_TARBALL", musl)
    environment = FakeEnvironment(musl=True)

    await make_agent(la.LockedClaudeCode).install(environment)

    assert environment.uploaded == [musl]


async def test_claude_install_surfaces_rc_and_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    glibc = tmp_path / "claude.tgz"
    glibc.write_bytes(b"g")
    monkeypatch.setattr(la, "_CLAUDE_TARBALL", glibc)
    monkeypatch.setattr(la, "_CLAUDE_MUSL_TARBALL", tmp_path / "missing.tgz")
    environment = FakeEnvironment(
        musl=False,
        rc=127,
        stdout="bash: /usr/local/bin/claude: cannot execute: required file not found",
        stderr=None,
    )

    with pytest.raises(RuntimeError) as excinfo:
        await make_agent(la.LockedClaudeCode).install(environment)

    text = str(excinfo.value)
    assert "rc=127" in text
    assert "required file not found" in text


async def test_opencode_install_uploads_musl_tarball_on_musl_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    glibc = tmp_path / "opencode.tgz"
    musl = tmp_path / "opencode-musl.tgz"
    glibc.write_bytes(b"g")
    musl.write_bytes(b"m")
    monkeypatch.setattr(la, "_OPENCODE_TARBALL", glibc)
    monkeypatch.setattr(la, "_OPENCODE_MUSL_TARBALL", musl)
    environment = FakeEnvironment(musl=True)

    await make_agent(la.LockedOpenCode).install(environment)

    assert environment.uploaded == [musl]


async def test_opencode_install_surfaces_rc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    glibc = tmp_path / "opencode.tgz"
    glibc.write_bytes(b"g")
    monkeypatch.setattr(la, "_OPENCODE_TARBALL", glibc)
    environment = FakeEnvironment(musl=False, rc=127, stdout="cannot execute")

    with pytest.raises(RuntimeError, match="opencode install failed: rc=127"):
        await make_agent(la.LockedOpenCode).install(environment)
