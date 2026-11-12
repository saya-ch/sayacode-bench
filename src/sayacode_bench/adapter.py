"""Harbor 0.24 installed adapter：只安装和运行 SAYACODE，不解释任务答案。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .installation import bundled_uv_installer, prepare_uv_installer, verify_installed_runtime
from .noise import stage_background
from .worker import audit_metrics, read_object, variant_profile, write_json

ROOT = PurePosixPath("/installed-agent/sayacode")
PRIVATE = PurePosixPath("/installed-agent/sayacode-private")


class SayacodeAgent(BaseInstalledAgent):  # type: ignore[misc]
    """生产 wheel 与锁文件固定安装，连接通过权限受限的文件传递。"""

    ERROR_PATTERNS: ClassVar[list[Any]] = []
    DEFAULT_SETUP_TIMEOUT_SEC = 2400.0

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
        evidence = self.logs_dir / "installation"
        # 优先使用仓库预置的 install.sh；只有本地不可用时才回退在线下载。
        # 在线下载仍受网络抖动影响（curl exit=18 传输中断等）；在此重试 3 次。
        local_installer = bundled_uv_installer()
        bootstrap: dict[str, Any] | None = None
        for attempt in range(1, 4):
            try:
                bootstrap = await prepare_uv_installer(
                    environment,
                    ROOT / "install-uv.sh",
                    evidence,
                    self.ensure_system_dependencies,
                    local_installer=local_installer,
                )
                break
            except RuntimeError as exc:
                if "curl exit=" not in str(exc) or attempt == 3:
                    raise
                await asyncio.sleep(5)
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
        # CPython 由宿主预置上传，而不是让 uv 在 trial 里现下载。
        #
        # 原实现只有 ``uv python install <ver>``，它需要访问
        # github.com/astral-sh/python-build-standalone。该主机在 trial 容器内
        # 不可达（网络隔离只放行模型网关），2026-11-12 的 100 题实验里
        # 表现为 ``tls handshake eof``，sayacode 32 个 trial 中有 21 个栽在
        # 安装阶段被记为 infrastructure_error——而 claude-code / opencode
        # 用的是预置 tarball，同期 0 个安装失败。这个偏差会让 sayacode 的
        # 有效分母塌到 11 题，足以把对比结论整体带偏。
        #
        # 解压放在 ROOT 下（**不能**放 PRIVATE：那是 chmod 700 的私有目录，
        # agent 用户无法穿过它执行解释器）。是否可用的判定放在安装脚本内部
        # 用 ``[ -x ... ]`` 现场做，而不是靠 Python 侧的跨调用布尔量——
        # 上一版正是把「上传/解压成功」当成「解释器可用」，解压后路径不存在
        # 时仍然把绝对路径塞给 uv，三个 attempt 全报
        # "No interpreter found at path"，却没人知道解压其实没落地。
        py_dir = f"{ROOT}/py313"
        py_bin = f"{py_dir}/python/bin/python3.13"
        py_tar = Path(os.environ.get("SAYACODE_PY313_TARBALL", r"C:\sb\tmp\hard\py313.tar.gz"))
        if py_tar.is_file():
            try:
                await environment.upload_file(py_tar, "/tmp/py313.tar.gz")
                await self.exec_as_root(
                    environment,
                    command=(
                        f"rm -rf {py_dir}; mkdir -p {py_dir}; "
                        f"tar -xzf /tmp/py313.tar.gz -C {py_dir} && "
                        f"rm -f /tmp/py313.tar.gz && "
                        f"chmod -R a+rX {py_dir}"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(f"py313 预置失败（{str(exc)[:120]}），回退到 uv 下载")
        # ⚠️ 这里每步之间必须用 `&&`，**不能**用 `;` 依赖 set -e。
        # POSIX 规定 set -e 在 if/while 的测试上下文里失效，而整条安装链被包在
        # `if ( set -eu; ... )` 里（见下方重试循环）。实测（2026-11-08）：
        #   if ( set -eu; echo a; false; echo b ); then ok=1; fi
        # 会输出 a、b 并且 ok=1 —— 中间失败被吞掉，最后一条 chmod 成功就返回 0。
        # 后果：安装失败不会触发重试，一路拖到 verify_installed_runtime 才报
        # 「安装后 version 检查失败」，错误信息完全误导。v2 实验里 20 个 trial
        # 有 7 个栽在这里，每个只花 20 秒。
        install_steps = (
            f"export UV_PYTHON_INSTALL_DIR={ROOT}/python && "
            # 慢速网络适配：国内 PyPI 镜像 + 放宽 uv 的 HTTP 超时与并发。
            "export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple && "
            "export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple && "
            "export UV_HTTP_TIMEOUT=600 UV_CONCURRENT_DOWNLOADS=4 && "
            # 确保 {ROOT}/bin/uv 始终可用，绕过「本地 installer 跳过 ensure_curl、
            # 但 install-uv.sh 自身仍需要 curl/wget」的死结（3.2.6 起本地 installer 优先）。
            # 顺序按可靠性排列：
            #   1) 有 pip3 → 从国内 PyPI 源装 uv（最可靠；容器内 astral.sh 可能 403/不稳定，
            #      有 curl 的镜像走 install-uv.sh 反而会失败）；
            #   2) 系统/镜像已有 uv → 直接软链；
            #   3) 有 curl/wget 且无 pip3 → 回退本地 install-uv.sh；
            #   4) 都没有 → 报错退出（不再静默跳过，避免后续 rc=127 难定位）。
            f"mkdir -p {ROOT}/bin && "
            # 三级回退必须是**真回退**：原来的写法是
            #   if pip3; then (pip3 install uv) && ln -sf ...; elif uv; ... elif curl; ... fi
            # pip3 装失败时整条 if 分支直接失败，不会进 elif，于是
            # 「有 pip3 但没有 uv」的镜像永远装不上。
            # 2026-11-11 实测：python3.9 的 pip 21.0.1 装 uv 必崩
            # （KeyError: 'uv' / TypeError: 'str' object is not callable），
            # sayacode 因此拿到大量 NonZeroAgentExitCodeError。
            # 改成逐级尝试，任一级成功即返回。
            "_setup_uv() { "
            "if command -v pip3 >/dev/null 2>&1; then "
            "( pip3 install -q --break-system-packages uv -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null "
            "|| pip3 install -q uv -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null ) "
            f"&& command -v uv >/dev/null 2>&1 && ln -sf \"$(readlink -f \"$(command -v uv)\")\" {ROOT}/bin/uv && return 0; "
            "fi; "
            "if command -v uv >/dev/null 2>&1; then "
            f"ln -sf \"$(readlink -f \"$(command -v uv)\")\" {ROOT}/bin/uv && return 0; "
            "fi; "
            "if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then "
            f"env UV_INSTALL_DIR={ROOT}/bin UV_NO_MODIFY_PATH=1 sh {ROOT}/install-uv.sh >/dev/null 2>&1 "
            f"&& [ -x {ROOT}/bin/uv ] && return 0; "
            "fi; "
            "return 1; "
            "}; "
            f"_setup_uv || {{ echo 'no pip3/uv/curl available' >&2; exit 1; }} && "
            # 解释器选择在 shell 里现场判定：预置目录里真有可执行文件就用绝对
            # 路径，否则回退 ``uv python install``。这样「预置失败」不会静默
            # 变成「拿一个不存在的路径去建 venv」。
            f"_py_expr() {{ if [ -x {py_bin} ]; then echo {py_bin}; else echo {shlex.quote(self.python_version)}; fi; }} && "
            f"_py=$(_py_expr) && "
            f"if [ \"$_py\" = {shlex.quote(self.python_version)} ]; then "
            f"{ROOT}/bin/uv python install {shlex.quote(self.python_version)}; fi && "
            # --clear：/installed-agent/sayacode/venv 可能已存在（镜像预置、
            # 或 Harbor 重试复用容器）。不加 --clear 时 uv 直接报
            # 「Use the --clear flag or set UV_VENV_CLEAR=1」并退出，
            # 整条安装链失败。2026-11-10 第 3 批实测踩到：
            # protonmail-webclients-09fcf0db 三次 attempt 全失败。
            f"{ROOT}/bin/uv venv --clear --python \"$_py\" {ROOT}/venv && "
            f"{ROOT}/bin/uv pip install --python {ROOT}/venv/bin/python --require-hashes "
            f"-r {ROOT}/requirements.txt && "
            f"{ROOT}/bin/uv pip install --python {ROOT}/venv/bin/python --no-deps "
            f"{shlex.quote(str(ROOT / self.product_wheel.name))} && "
            # uv 下载的 Python 分发包偶发 pyc 损坏，表现为 import 链中途抛
            # ``ValueError: bad marshal data (invalid reference)``，
            # 而且报在标准库 import 上，看起来像产品依赖坏了，极难定位。
            # 2026-11-10 的 40 题 x 4 agent 实验里，sayacode 因此拿到 3 个
            # infrastructure_error（安装后 imports 检查失败），被记成 reward=0。
            # 清掉 pycache 让解释器重新编译（只删目录，源码不动）。
            # 用括号包住 || true，保证它不会截断外层的 && 链——
            # 否则 chmod 会变成独立语句，前面全失败也照样返回 0
            # （同 L99-103 注释里那个 set -e 陷阱）。
            f"( find {ROOT}/python {ROOT}/venv -name __pycache__ -type d "
            "-prune -exec rm -rf {} + 2>/dev/null || true ) && "
            f"chmod -R a+rX {ROOT}"
        )
        install_result = await self.exec_as_root(
            environment,
            # astral.sh/GitHub 的下载间歇性 TLS 失败；整链重试 3 次（下载失败 20 秒即返回，代价小）。
            command=(
                "set -u; ok=0; "
                "for attempt in 1 2 3; do "
                f"if ( {install_steps} ); then ok=1; break; fi; "
                'echo "install attempt $attempt failed, retrying"; sleep 5; done; '
                '[ "$ok" = 1 ]'
            ),
        )
        # 安装命令本身的返回码必须检查：否则失败会静默滑到 verify 阶段，
        # 报成「安装后 version 检查失败」，把最简单的原因藏起来。
        install_code = getattr(install_result, "return_code", 0)
        if install_code:
            raise RuntimeError(f"SAYACODE 安装命令失败，返回码 {install_code}")
        if bootstrap is None:
            raise RuntimeError("uv 安装引导未完成")
        await verify_installed_runtime(
            environment,
            ROOT,
            evidence,
            bootstrap,
            wheel=self.product_wheel,
            requirements=self.requirements_path,
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
        # 长上下文实验：把背景材料放进容器内文件，instruction 只加固定短提示。
        # 与三个基线走完全相同的函数（sayacode_bench.noise），保证四组输入一致。
        instruction = await stage_background(instruction, environment)
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
