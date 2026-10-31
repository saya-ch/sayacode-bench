"""正式对比的 agent 构造与输入路径。

收编自仓外 ``C:\\sb\\hard\\test_agent.py``、``C:\\sb\\hard\\locked_mini_swe_fixed.py`` 与
``tooling/locked_codex.py``、``tooling/patch_replay.py``。仓外路径全部集中在 :class:`FormalPaths`，
可用构造参数或 ``SAYACODE_BENCH_*`` 环境变量覆盖；仓库内不再 ``sys.path.insert`` 指向 ``C:\\sb\\hard``。

三个 agent 的规范模型身份统一为 ``auto-hy3``（见 ``studies/execution-protocol-v13.json`` 与
``magpie-hy3.json`` 的 ``model_id``）；``DeepSeek-V4.1-Flash`` 只是 SAYACODE 产品 profile 的内部别名。
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from harbor.agents.base import BaseAgent  # noqa: E402
from harbor.agents.installed.codex import Codex  # noqa: E402
from harbor.agents.installed.mini_swe_agent import MiniSweAgent  # noqa: E402
from harbor.environments.base import BaseEnvironment  # noqa: E402
from harbor.models.agent.context import AgentContext  # noqa: E402
from harbor.models.trial.config import AgentConfig, EnvironmentConfig  # noqa: E402

CANONICAL_MODEL = "auto-hy3"
AGENTS = ("sayacode", "mini-swe", "codex")
IN_SANDBOX_GATEWAY = "http://saya-model-gateway:8080"
DEFAULT_GATEWAY = "http://host.docker.internal:3425/v1"
DEFAULT_TASKS_ROOT = (
    r"C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
)
# 当前有效输入（v2 重建批次）。复现 v1 历史批次时用 SAYACODE_BENCH_PROFILE /
# SAYACODE_BENCH_WHEEL 指回 C:\sb\hard\magpie-hy3.json 与
# C:\sb\tmp\hard\wheel-release\out\sayacode-3.2.4-py3-none-any.whl。
DEFAULT_PROFILE = r"C:\sb\hard\magpie-hy3-v2.json"
DEFAULT_WHEEL = r"C:\sb\tmp\hard\wheel-release-3.2.5\out\sayacode-3.2.5-py3-none-any.whl"
DEFAULT_REQUIREMENTS = (
    r"C:\sb\r\formal-study-v1\prepared-original\mapped-bundle\inputs\product-requirements.txt"
)
DEFAULT_VARIANT = r"C:\sb\r\formal-study-v1\prepared-original\mapped-bundle\inputs\baseline.json"


def _env_path(name: str, default: str | Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else Path(default)


@dataclass(frozen=True)
class FormalPaths:
    """正式运行的仓外输入；默认值只为复现历史批次，正式使用应显式指定。"""

    tasks_root: Path = Path(DEFAULT_TASKS_ROOT)
    profile: Path = Path(DEFAULT_PROFILE)
    wheel: Path = Path(DEFAULT_WHEEL)
    requirements: Path = Path(DEFAULT_REQUIREMENTS)
    variant: Path = Path(DEFAULT_VARIANT)
    gateway: str = DEFAULT_GATEWAY
    sample: Path = ROOT / "studies" / "sample-40-final.json"
    mini_config: Path = ROOT / "scripts" / "formal_configs" / "mini_toolcall.yaml"
    codex_tarball: Path | None = None
    out_root: Path = ROOT / "results" / "formal"

    @property
    def tooling(self) -> Path:
        """任务缓存里的 tooling 目录（只含数据与配置，不再是代码导入路径）。"""
        return self.tasks_root.parent / "tooling"

    def resolved_codex_tarball(self) -> Path:
        if self.codex_tarball is not None:
            return self.codex_tarball
        return self.tooling / "bin" / "codex-slim-0.155.1.tar.gz"

    @classmethod
    def from_env(cls, **overrides: Any) -> FormalPaths:
        base = cls(
            tasks_root=_env_path("SAYACODE_BENCH_TASKS_ROOT", DEFAULT_TASKS_ROOT),
            profile=_env_path("SAYACODE_BENCH_PROFILE", DEFAULT_PROFILE),
            wheel=_env_path("SAYACODE_BENCH_WHEEL", DEFAULT_WHEEL),
            requirements=_env_path("SAYACODE_BENCH_REQUIREMENTS", DEFAULT_REQUIREMENTS),
            variant=_env_path("SAYACODE_BENCH_VARIANT", DEFAULT_VARIANT),
            gateway=os.environ.get("SAYACODE_BENCH_GATEWAY", DEFAULT_GATEWAY),
            sample=_env_path("SAYACODE_BENCH_SAMPLE", ROOT / "studies" / "sample-40-final.json"),
            mini_config=_env_path(
                "SAYACODE_BENCH_MINI_CONFIG", ROOT / "scripts" / "formal_configs" / "mini_toolcall.yaml"
            ),
            codex_tarball=(
                Path(os.environ["SAYACODE_BENCH_CODEX_TARBALL"])
                if os.environ.get("SAYACODE_BENCH_CODEX_TARBALL")
                else None
            ),
            out_root=_env_path("SAYACODE_BENCH_OUT_ROOT", ROOT / "results" / "formal"),
        )
        return cls(**{**base.__dict__, **overrides})

    def require_inputs(self, *, agent: str) -> None:
        """按 agent 检查必要输入，缺失时给出可操作的错误而不是静默降级。"""
        required = [self.tasks_root]
        if agent == "sayacode":
            required.extend([self.profile, self.wheel, self.requirements, self.variant])
        if agent == "mini-swe":
            required.append(self.mini_config)
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError("缺少正式运行输入：" + "；".join(missing))


def env_cfg(paths: FormalPaths) -> EnvironmentConfig:
    """容器内通过 host.docker.internal 回到宿主网关，其余流量由隔离网络拦断。"""
    gateway = paths.gateway.rstrip("/")
    return EnvironmentConfig(
        import_path="sayacode_bench.network:IsolatedDockerEnvironment",
        kwargs={
            "messages_upstream": gateway + "/messages",
            "chat_upstream": gateway + "/chat/completions",
            "responses_upstream": gateway + "/responses",
        },
    )


_CAPTURE = (
    "pkill -f '[m]ini-swe-agent --yolo' >/dev/null 2>&1; sleep 3; "
    "mkdir -p /logs/agent; "
    "repo=$(git -C /app rev-parse --show-toplevel 2>/dev/null || git -C /testbed rev-parse --show-toplevel 2>/dev/null || echo /app); "
    'cd "$repo" && git add -A 2>/dev/null; git diff --cached > /logs/agent/model.patch 2>/dev/null; git reset -q 2>/dev/null; '
    "wc -c < /logs/agent/model.patch; true"
)
_CAPTURE_CODEX = _CAPTURE.replace("pkill -f '[m]ini-swe-agent --yolo' >/dev/null 2>&1; sleep 3; ", "")


class LockedMiniSwe(MiniSweAgent):
    """上游 mini-swe-agent + 稳定安装 + 收尾时抓取 model.patch。"""

    @staticmethod
    def name() -> str:
        return "mini-swe-agent-locked"

    async def install(self, environment: BaseEnvironment) -> None:
        try:
            await self.ensure_system_dependencies(
                environment, ("curl", "bash", "build_tools", "git", "python3", "python_pip")
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                f"apt install failed ({str(exc)[:100]}); retrying against archive.debian.org"
            )
            await environment.exec(
                command=(
                    "sed -i -e 's|deb.debian.org/debian-security|archive.debian.org/debian-security|g' "
                    "-e 's|security.debian.org|archive.debian.org|g' "
                    "-e 's|deb.debian.org|archive.debian.org|g' -e '/buster-updates/d' -e '/bullseye-updates/d' "
                    "/etc/apt/sources.list 2>/dev/null; "
                    'echo \'Acquire::Check-Valid-Until "false";\' > /etc/apt/conf.d/99no-check-valid 2>/dev/null || true; '
                    "apt-get -o Acquire::Check-Valid-Until=false update >/dev/null 2>&1; "
                    "apt-get install -y --no-install-recommends curl bash git python3 python3-pip "
                    "build-essential >/dev/null 2>&1 || true"
                ),
                user="root",
                timeout_sec=900,
            )
            check = await environment.exec(
                command="command -v curl && command -v git && command -v bash && echo TOOLS_OK",
                user="root",
                timeout_sec=60,
            )
            if "TOOLS_OK" not in (check.stdout or ""):
                raise
            self.logger.warning("required tools present after archive.debian.org retry; continuing")
        version_spec = f"=={self._version}" if self._version else ""
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "if ! command -v uv >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi && "
                'if ! grep -q \'export PATH="$HOME/.local/bin:$PATH"\' "$HOME/.bashrc" 2>/dev/null; then'
                '  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> "$HOME/.bashrc"; fi && '
                'if [ -f "$HOME/.local/bin/env" ]; then source "$HOME/.local/bin/env"; fi && '
                'export PATH="$HOME/.local/bin:$PATH" && '
                f"uv tool install --python 3.12 mini-swe-agent{version_spec} "
                "--with litellm --with orjson --with fastapi --with mcp && mini-swe-agent --help"
            ),
        )

    async def exec_as_agent(self, environment: BaseEnvironment, command: str, **kwargs: Any) -> Any:
        """把 agent 调用包进沙箱内 timeout（预算 - 60 秒），避免客户端取消不了卡死的流。"""
        if "mini-swe-agent --yolo" in command:
            budget = int(getattr(self, "_timeout_sec", None) or 3000) - 60
            command = f"timeout -k 30 {budget} bash -c {shlex.quote(command)}"
        return await super().exec_as_agent(environment, command, **kwargs)

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            try:
                result = await environment.exec(command=_CAPTURE, user="root", timeout_sec=300)
                self.logger.info(f"model.patch bytes: {(result.stdout or '').strip()}")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"patch capture failed: {exc}")


class LockedCodex(Codex):
    """上游 Codex CLI + 固定版本二进制 + 收尾时抓取 model.patch。"""

    @staticmethod
    def name() -> str:
        return "codex-locked"

    tarball_path: Path | None = None
    _URL = (
        "https://github.com/openai/codex/releases/download/rust-v0.155.1/"
        "codex-package-x86_64-unknown-linux-musl.tar.gz"
    )
    _SHA = "a65b895c6ac1a73629bbe4b864640c86133e94a43b4d67b3103044e1a306d5a2"
    _EXTRACT = (
        "cd /tmp && rm -rf codexpkg && mkdir codexpkg && "
        "tar xzf codex.tar.gz -C codexpkg bin/codex bin/codex-code-mode-host codex-path/rg "
        "&& install -m 755 codexpkg/bin/codex codexpkg/bin/codex-code-mode-host /usr/local/bin/ "
        "&& { command -v rg >/dev/null 2>&1 || install -m 755 codexpkg/codex-path/rg /usr/local/bin/rg; } "
        "&& rm -rf codex.tar.gz codexpkg && codex --version && ls /usr/local/bin/codex-code-mode-host"
    )

    async def install(self, environment: BaseEnvironment) -> None:
        url, sha = self._URL, self._SHA
        fetch = (
            "set -e; cd /tmp && rm -f codex.tar.gz; "
            f"if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -m 240 -o codex.tar.gz {url}; "
            f"elif command -v wget >/dev/null 2>&1; then wget -q -T 240 -t 3 -O codex.tar.gz {url}; "
            "elif command -v python3 >/dev/null 2>&1; then python3 -c 'import urllib.request,sys; "
            'urllib.request.urlretrieve(sys.argv[1], "codex.tar.gz")\' '
            f"{url}; "
            "elif command -v apt-get >/dev/null 2>&1; then (apt-get update -qq && apt-get install -y -qq curl) "
            f">/dev/null 2>&1 && curl -fsSL --retry 3 -m 240 -o codex.tar.gz {url}; "
            "else echo NO_DOWNLOADER; exit 3; fi; "
            f"echo '{sha}  codex.tar.gz' | sha256sum -c - && echo FETCHED"
        )
        result = await environment.exec(command=fetch, user="root", timeout_sec=280)
        if result.return_code != 0 or "FETCHED" not in (result.stdout or ""):
            self.logger.warning(
                f"in-sandbox fetch failed (rc={result.return_code}): {(result.stderr or '')[:200]} — "
                "falling back to upload"
            )
            tarball = self.tarball_path
            if tarball is None or not tarball.is_file():
                raise RuntimeError(f"codex 下载失败且没有可上传的 tarball：{tarball}")
            await environment.upload_file(tarball, "/tmp/codex.tar.gz")
            extract = self._EXTRACT.replace(
                " bin/codex bin/codex-code-mode-host codex-path/rg", ""
            )
        else:
            extract = self._EXTRACT
        result = await environment.exec(command="set -e; " + extract, user="root", timeout_sec=120)
        self.logger.info(
            f"codex install: rc={result.return_code} {(result.stdout or '').strip()} "
            f"{(result.stderr or '').strip()[:200]}"
        )
        if result.return_code != 0:
            raise RuntimeError(f"codex install failed: {result.stderr}")

    async def exec_as_agent(self, environment: BaseEnvironment, command: str, **kwargs: Any) -> Any:
        if "codex exec" in command:
            budget = int(getattr(self, "_timeout_sec", None) or 3000) - 60
            command = f"timeout -k 30 {budget} bash -c {shlex.quote(command)}"
        return await super().exec_as_agent(environment, command, **kwargs)

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            try:
                result = await environment.exec(command=_CAPTURE_CODEX, user="root", timeout_sec=300)
                self.logger.info(f"model.patch bytes: {(result.stdout or '').strip()}")
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"patch capture failed: {exc}")


class PatchReplayAgent(BaseAgent):
    """把上一阶段 job 的 ``agent/model.patch`` 在干净沙箱重放，消除验证器被篡改的可能。"""

    def __init__(self, *args: Any, source_job: str, patch_name: str = "model.patch", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._source_job = Path(source_job)
        self._patch_name = patch_name

    @staticmethod
    def name() -> str:
        return "patch-replay-agent"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    def _find_patch(self, task_name: str) -> Path | None:
        for result_json in self._source_job.glob("instance_*/result.json"):
            try:
                payload = json.loads(result_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(payload.get("task_name", "")).split("/")[-1] == task_name:
                patch = result_json.parent / "agent" / self._patch_name
                return patch if patch.exists() else None
        return None

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        try:
            config = json.loads((self.logs_dir.parent / "config.json").read_text(encoding="utf-8"))
            task_name = Path(config["task"]["path"]).name
        except (OSError, ValueError, KeyError, TypeError):
            task_name = self.logs_dir.parent.name
        patch = self._find_patch(task_name)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if patch is None or patch.stat().st_size == 0:
            self.logger.warning(f"no source patch for {task_name}; applying nothing")
            (self.logs_dir / "replay.json").write_text(
                json.dumps({"task": task_name, "patch": None}), encoding="utf-8"
            )
            return
        await environment.upload_file(source_path=patch, target_path="/tmp/replay.patch")
        applied = await environment.exec(
            command="cd /app 2>/dev/null || cd /testbed; git apply --verbose /tmp/replay.patch "
            "|| git apply --3way /tmp/replay.patch || patch --fuzz=3 -p1 -i /tmp/replay.patch",
            timeout_sec=300,
        )
        stat = await environment.exec(
            command="cd /app 2>/dev/null || cd /testbed; git --no-pager diff --stat | tail -n 40; "
            "echo ---; git status --short | wc -l",
            timeout_sec=120,
        )
        (self.logs_dir / "replay.json").write_text(
            json.dumps(
                {
                    "task": task_name,
                    "patch": str(patch),
                    "apply_rc": applied.return_code,
                    "apply_out": ((applied.stdout or "") + (applied.stderr or ""))[-6000:],
                    "post_apply_diffstat": (stat.stdout or "")[-3000:],
                },
                indent=1,
            ),
            encoding="utf-8",
        )


class NoOpAgent(BaseAgent):
    """不修改任何文件；用于 NOP 门禁（无修复时题必须失败）。"""

    @staticmethod
    def name() -> str:
        return "no-op-agent"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "model.patch").write_text("", encoding="utf-8")


def build_agent(name: str, paths: FormalPaths, *, profile_dir: Path | None = None) -> AgentConfig:
    """构造三 agent 之一；规范模型身份统一为 ``auto-hy3``。"""
    if name == "sayacode":
        import re

        from sayacode_bench import installation as _installation

        # 从 wheel 文件名推断产品版本，避免 bump 后 installation.PRODUCT_VERSION 漏改。
        match = re.search(r"sayacode-(\d+\.\d+\.\d+)-", paths.wheel.name)
        if match:
            _installation.PRODUCT_VERSION = match.group(1)
        profile = json.loads(paths.profile.read_text(encoding="utf-8"))
        profile["base_url"] = IN_SANDBOX_GATEWAY
        private = (profile_dir or paths.out_root) / "profile-private.json"
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(json.dumps(profile), encoding="utf-8")
        return AgentConfig(
            import_path="sayacode_bench.adapter:SayacodeAgent",
            model_name="DeepSeek-V4.1-Flash",
            extra_allowed_hosts=["saya-model-gateway"],
            kwargs={
                "product_wheel": str(paths.wheel),
                "requirements_path": str(paths.requirements),
                "profile_path": str(private),
                "variant_path": str(paths.variant),
            },
        )
    if name == "mini-swe":
        return AgentConfig(
            import_path="locked_agents:LockedMiniSwe",
            model_name="openai/auto-hy3",
            extra_allowed_hosts=["saya-model-gateway"],
            override_setup_timeout_sec=1800,
            env={
                "OPENAI_API_KEY": "magpie",
                "MSWEA_API_KEY": "magpie",
                "OPENAI_BASE_URL": IN_SANDBOX_GATEWAY + "/v1",
                "OPENAI_API_BASE": IN_SANDBOX_GATEWAY + "/v1",
                "PIP_INDEX_URL": "https://pypi.tuna.tsinghua.edu.cn/simple",
                "UV_DEFAULT_INDEX": "https://pypi.tuna.tsinghua.edu.cn/simple",
                "UV_INDEX_URL": "https://pypi.tuna.tsinghua.edu.cn/simple",
            },
            kwargs={
                "config_file": str(paths.mini_config),
                "reasoning_effort": "high",
                "litellm_model_registry": {
                    "openai/auto-hy3": {
                        "max_tokens": 32000,
                        "max_input_tokens": 176000,
                        "max_output_tokens": 32000,
                        "input_cost_per_token": 0.0,
                        "output_cost_per_token": 0.0,
                        "litellm_provider": "openai",
                        "mode": "chat",
                    }
                },
            },
        )
    if name == "codex":
        LockedCodex.tarball_path = paths.resolved_codex_tarball()
        return AgentConfig(
            import_path="locked_agents:LockedCodex",
            model_name=CANONICAL_MODEL,
            extra_allowed_hosts=["saya-model-gateway"],
            env={
                "OPENAI_API_KEY": "magpie",
                "OPENAI_BASE_URL": IN_SANDBOX_GATEWAY + "/v1",
                "OPENAI_API_BASE": IN_SANDBOX_GATEWAY + "/v1",
            },
            kwargs={
                "reasoning_effort": "high",
                "web_search": "disabled",
                "config": {"model_context_window": 192000, "model_max_output_tokens": 32000},
            },
        )
    raise SystemExit(f"unknown agent {name}")


__all__ = [
    "AGENTS",
    "CANONICAL_MODEL",
    "DEFAULT_GATEWAY",
    "FormalPaths",
    "IN_SANDBOX_GATEWAY",
    "LockedCodex",
    "LockedMiniSwe",
    "NoOpAgent",
    "PatchReplayAgent",
    "ROOT",
    "build_agent",
    "env_cfg",
]
