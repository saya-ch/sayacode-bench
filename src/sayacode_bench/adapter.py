"""Harbor 0.24 installed adapter：只安装和运行 SAYACODE，不解释任务答案。"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .worker import audit_metrics, read_object, variant_profile, write_json

ROOT = PurePosixPath("/installed-agent/sayacode")
PRIVATE = PurePosixPath("/installed-agent/sayacode-private")


class SayacodeAgent(BaseInstalledAgent):  # type: ignore[misc]
    """生产 wheel 与锁文件固定安装，连接通过权限受限的文件传递。"""

    ERROR_PATTERNS: ClassVar[list[Any]] = []
    DEFAULT_SETUP_TIMEOUT_SEC = 900.0

    @staticmethod
    def name() -> str:
        return "sayacode"

    def __init__(
        self,
        logs_dir: Path,
        *,
        product_wheel: str,
        profile_path: str,
        variant_path: str,
        requirements_path: str,
        prompt_path: str | None = None,
        python_version: str = "3.13.7",
        **kwargs: Any,
    ) -> None:
        self.product_wheel = Path(product_wheel).resolve(strict=True)
        self.requirements_path = Path(requirements_path).resolve(strict=True)
        self.profile_path = Path(profile_path).resolve(strict=True)
        self.variant_path = Path(variant_path).resolve(strict=True)
        self.prompt_path = Path(prompt_path).resolve(strict=True) if prompt_path else None
        if not self.product_wheel.name.endswith(".whl"):
            raise ValueError("product_wheel 必须是构建完成的 wheel")
        if re.fullmatch(r"3\.13\.[0-9]+", python_version) is None:
            raise ValueError("固定 Python 版本必须为 3.13.x")
        self.python_version = python_version
        variant_profile(read_object(self.profile_path), read_object(self.variant_path))
        super().__init__(logs_dir, **kwargs)
        if self.mcp_servers or self.skills_dir:
            raise ValueError("本实验不注入 Harbor MCP 或额外 Skills")

    def get_version_command(self) -> str:
        return f"{ROOT}/venv/bin/sayacode --version"

    async def install(self, environment: BaseEnvironment) -> None:
        await self.ensure_system_dependencies(environment, ("curl", "ca_certificates"))
        await self.exec_as_root(
            environment, command=f"mkdir -p {ROOT} {PRIVATE}; chmod 700 {PRIVATE}"
        )
        for source, target in (
            (self.product_wheel, ROOT / "product.whl"),
            (self.requirements_path, ROOT / "requirements.txt"),
            (Path(__file__).with_name("worker.py"), ROOT / "worker.py"),
        ):
            # wheel 必须保持合法文件名，pip 从文件名读取发行物元数据。
            remote = ROOT / source.name if source == self.product_wheel else target
            await environment.upload_file(source, str(remote))
        await self.exec_as_root(
            environment,
            command=(
                f"set -eu; export UV_PYTHON_INSTALL_DIR={ROOT}/python; "
                f"curl -LsSf https://astral.sh/uv/0.12.5/install.sh -o {ROOT}/install-uv.sh; "
                f"env UV_INSTALL_DIR={ROOT}/bin UV_NO_MODIFY_PATH=1 sh {ROOT}/install-uv.sh; "
                f"{ROOT}/bin/uv python install {shlex.quote(self.python_version)}; "
                f"{ROOT}/bin/uv venv --python {shlex.quote(self.python_version)} {ROOT}/venv; "
                f"{ROOT}/bin/uv pip install --python {ROOT}/venv/bin/python --require-hashes "
                f"-r {ROOT}/requirements.txt; "
                f"{ROOT}/bin/uv pip install --python {ROOT}/venv/bin/python --no-deps "
                f"{shlex.quote(str(ROOT / self.product_wheel.name))}; "
                f"chmod -R a+rX {ROOT}"
            ),
        )

    async def _upload(
        self, environment: BaseEnvironment, source: Path, target: PurePosixPath
    ) -> None:
        await environment.upload_file(source, str(target))
        owner = environment.default_user
        ownership = f"chown {shlex.quote(str(owner))} {shlex.quote(str(target))}; " if owner else ""
        await self.exec_as_root(
            environment, command=f"{ownership}chmod 600 {shlex.quote(str(target))}"
        )

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        logs = self.environment_logs_dir / "sayacode"
        owner = environment.default_user
        ownership = f"chown {shlex.quote(str(owner))} {PRIVATE} {logs}; " if owner else ""
        await self.exec_as_root(environment, command=f"set -eu; mkdir -p {logs}; {ownership}true")
        await self._upload(environment, self.profile_path, PRIVATE / "profile.json")
        variant = read_object(self.variant_path)
        if self.prompt_path:
            original = variant.get("instruction_append", "")
            variant["instruction_append"] = "\n\n".join(
                part for part in (original, self.prompt_path.read_text(encoding="utf-8")) if part
            )
        with tempfile.TemporaryDirectory(prefix="sayacode-harbor-") as directory:
            local = Path(directory)
            (local / "variant.json").write_text(json.dumps(variant), encoding="utf-8")
            (local / "instruction.txt").write_text(instruction, encoding="utf-8")
            await self._upload(environment, local / "variant.json", PRIVATE / "variant.json")
            await self._upload(environment, local / "instruction.txt", PRIVATE / "instruction.txt")
        command = (
            f"{ROOT}/venv/bin/python {ROOT}/worker.py --profile {PRIVATE}/profile.json "
            f"--variant {PRIVATE}/variant.json --instruction {PRIVATE}/instruction.txt "
            f"--state {PRIVATE}/state --logs {logs} > {logs}/worker.log 2>&1"
        )
        await self.exec_as_agent(
            environment,
            command=f"{ROOT}/venv/bin/python {ROOT}/worker.py --capture-base {logs}/git-base.json",
        )
        try:
            result = await environment.exec(command=command)
            if result.return_code:
                raise NonZeroAgentExitCodeError(f"SAYACODE worker exit={result.return_code}")
        finally:
            # 正常、失败和取消共用一次收尾；取消不能让验证器越过仍在运行的进程。
            finalizer = asyncio.create_task(self._finalize_worker(environment, logs))
            try:
                await asyncio.shield(finalizer)
            except asyncio.CancelledError:
                await finalizer
                raise

    async def _finalize_worker(self, environment: BaseEnvironment, logs: PurePosixPath) -> None:
        """先确认停止，再独立导出私有输出并采集补丁；导出错误不冒充运行失败。"""
        stopped = await environment.exec(
            command=f"{ROOT}/venv/bin/python {ROOT}/worker.py --stop {logs}/worker.pid.json",
            timeout_sec=25,
        )
        if stopped.return_code:
            raise RuntimeError("SAYACODE worker 停止未确认")
        try:
            exported = await environment.exec(
                command=f"{ROOT}/venv/bin/python {ROOT}/worker.py --export-outputs "
                f"--state-home {PRIVATE}/state/app --logs {logs}",
                timeout_sec=320,
            )
            export_status = {
                "command_status": "completed" if exported.return_code == 0 else "failed",
                "exit_code": exported.return_code,
                "error_type": None if exported.return_code == 0 else "OutputExportNonZeroExit",
            }
        except Exception as exc:
            export_status = {"command_status": "failed", "error_type": type(exc).__name__}
        try:
            # 命令状态不代替文件覆盖；覆盖详情见 sayacode/outputs-coverage.json 和清单。
            write_json(self.logs_dir / "tool-output-export.json", export_status)
        except OSError as exc:
            self.logger.warning("私有输出采集记录未保存：%s", type(exc).__name__)
        # 必须早于 Harbor verifier；官方 fresh-sandbox replay 只接收此文件。
        captured = await environment.exec(
            command=f"{ROOT}/venv/bin/python {ROOT}/worker.py --capture-final "
            f"{self.environment_logs_dir}/model.patch --base-file {logs}/git-base.json",
            timeout_sec=320,
        )
        if captured.return_code:
            raise RuntimeError("SAYACODE 最终补丁采集失败")

    def populate_context_post_run(self, context: AgentContext) -> None:
        path = self.logs_dir / "sayacode"
        result = read_object(path / "result.json") if (path / "result.json").is_file() else {}
        metrics = audit_metrics(path / "audit.jsonl")
        usage = metrics["usage"]
        if (
            usage["reported_calls"]
            and not usage["missing_usage_calls"]
            and not usage["damaged_audit_lines"]
        ):
            context.n_input_tokens = usage["input_tokens"]
            context.n_output_tokens = usage["output_tokens"]
        context.cost_usd = None
        context.metadata = {
            **(context.metadata or {}),
            "sayacode": {
                "status": result.get("status", "result_missing"),
                "task_count": result.get("task_count"),
                "variant_id": result.get("variant_id"),
                **metrics,
            },
        }
