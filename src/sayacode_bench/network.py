"""用 Docker 隔离桥与固定 nginx 网关实现本地评测的分阶段网络协议。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from harbor.environments.base import EnvironmentCapabilities
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import NetworkMode, NetworkPolicy

GATEWAY_HOST = "saya-model-gateway"
GATEWAY_BASE_URL = f"http://{GATEWAY_HOST}:8080"
NGINX_IMAGE = (
    "nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236"
)


@dataclass(frozen=True)
class GatewayConfig:
    """两个地址由研究配置固定；凭据只经请求头透传，不属于网关配置。"""

    chat_upstream: str | None
    messages_upstream: str


def _endpoint(value: str, suffix: str) -> tuple[str, str, str]:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme not in ("http", "https")
        or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(suffix)
        or not re.fullmatch(r"/[A-Za-z0-9/_.-]+", parsed.path)
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("模型网关地址必须是无凭据、无参数的固定 HTTP(S) API 路径")
    # 访问 port 属性也会拒绝非法端口；重建地址排除配置指令注入。
    authority = host + (f":{parsed.port}" if parsed.port is not None else "")
    return f"{parsed.scheme}://{authority}{parsed.path}", host, authority


def nginx_config(config: GatewayConfig) -> str:
    """只接受固定 API；Docker 桥使用 IPv4，DNS 不向不可达的 IPv6 地址轮询。"""

    locations = []
    groups = []
    for name, path, upstream in (
        ("saya_chat", "/v1/chat/completions", config.chat_upstream),
        ("saya_messages", "/v1/messages", config.messages_upstream),
    ):
        if upstream is None:
            continue
        url, host, authority = _endpoint(upstream, path)
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        groups.append(f"    upstream {name} {{ zone {name} 64k; server {host}:{port} resolve; }}")
        locations.append(
            f"""        location = {path} {{
            if ($request_method != POST) {{ return 405; }}
            if ($args != "") {{ return 400; }}
            proxy_set_header Host {authority};
            proxy_ssl_name {host};
            proxy_pass {parsed.scheme}://{name}{parsed.path};
        }}"""
        )
    return (
        """worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 128; }
http {
    resolver 127.0.0.11 ipv6=off valid=30s;
    resolver_timeout 10s;
    access_log off;
    server_tokens off;
    client_body_temp_path /tmp/client;
    proxy_temp_path /tmp/proxy;
    fastcgi_temp_path /tmp/fastcgi;
    uwsgi_temp_path /tmp/uwsgi;
    scgi_temp_path /tmp/scgi;
    client_max_body_size 64m;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Upgrade "";
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_next_upstream off;
    proxy_ignore_client_abort off;
    proxy_redirect off;
    proxy_connect_timeout 15s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_ssl_server_name on;
    proxy_ssl_verify on;
    proxy_ssl_verify_depth 5;
    proxy_ssl_trusted_certificate /etc/ssl/cert.pem;
"""
        + "\n".join(groups)
        + """
    server {
        listen 8080;
"""
        + "\n".join(locations)
        + """
        location / { return 404; }
    }
}
"""
    )


async def docker(
    *arguments: str, timeout: float = 90, check: bool = True, include_stderr: bool = False
) -> str:
    """只执行 Docker 的结构化参数；超时终止本次 CLI，不终止 Docker 服务。"""

    process = await asyncio.create_subprocess_exec(
        "docker",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        raise
    if check and process.returncode:
        raise RuntimeError(f"Docker 网络操作失败：{stderr.decode(errors='replace')[-1500:]}")
    output = stdout + (stderr if include_stderr else b"")
    return output.decode(errors="replace").strip()


class ModelGateway:
    """每个任务独立的网关和内部网，生命周期完全归属于该任务。"""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.config_text = nginx_config(config)
        token = uuid.uuid4().hex[:16]
        self.network = f"saya-isolated-{token}"
        self.container = f"saya-gateway-{token}"
        self._temporary: Path | None = None
        self.cleanup_errors: list[str] = []
        self.startup_log = ""

    async def start(self, external_network: str) -> None:
        self._temporary = Path(tempfile.mkdtemp(prefix="sayacode-nginx-"))
        config_path = self._temporary / "nginx.conf"
        config_path.write_text(self.config_text, encoding="utf-8", newline="\n")
        config_path.chmod(0o644)
        try:
            await docker(
                "network",
                "create",
                "--internal",
                "--opt",
                "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                "--label",
                "sayacode-bench.role=model-network",
                self.network,
            )
            await docker(
                "create",
                "--name",
                self.container,
                "--label",
                "sayacode-bench.role=model-gateway",
                "--network",
                external_network,
                "--read-only",
                "--user",
                "101:101",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--sysctl",
                "net.ipv4.ip_forward=0",
                "--sysctl",
                "net.ipv6.conf.all.forwarding=0",
                "--pids-limit",
                "64",
                "--memory",
                "128m",
                "--cpus",
                "0.25",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m,mode=1777",
                "--mount",
                f"type=bind,src={config_path.resolve()},dst=/etc/nginx/nginx.conf,readonly",
                NGINX_IMAGE,
                "nginx",
                "-g",
                "daemon off;",
                timeout=180,
            )
            await docker(
                "network", "connect", "--alias", GATEWAY_HOST, self.network, self.container
            )
            await docker("start", self.container)
            await docker("exec", self.container, "nginx", "-t")
            state = json.loads(await docker("inspect", self.container))
            if not state[0]["State"]["Running"]:
                raise RuntimeError("模型网关没有运行")
        except BaseException:
            self.startup_log = await docker(
                "logs", self.container, check=False, include_stderr=True
            )
            await self.close()
            raise

    async def close(self) -> None:
        self.cleanup_errors = []
        # 名称在构造时随机分配且只属于本任务；先查询存在性，避免把引擎异常当成已删除。
        for kind, name in (("container", self.container), ("network", self.network)):
            try:
                filter_name = f"name=^/{name}$" if kind == "container" else f"name=^{name}$"
                arguments = [kind, "ls"]
                if kind == "container":
                    arguments.append("--all")
                present = await docker(*arguments, "--filter", filter_name, "--format", "{{.ID}}")
                if present:
                    remove = (
                        ["rm", "--force", name] if kind == "container" else ["network", "rm", name]
                    )
                    await docker(*remove)
            except Exception as error:
                self.cleanup_errors.append(f"{kind}:{name}:{type(error).__name__}")
        if self.cleanup_errors:
            raise RuntimeError(
                "网络清理未确认，保留网关配置以便排查：" + ", ".join(self.cleanup_errors)
            )
        if self._temporary is not None:
            (self._temporary / "nginx.conf").unlink(missing_ok=True)
            self._temporary.rmdir()
            self._temporary = None


class IsolatedDockerEnvironment(DockerEnvironment):  # type: ignore[misc]
    """Harbor 原生 Docker 环境的本地网络适配；仅支持单个 Linux 容器。"""

    def __init__(
        self, *args: Any, messages_upstream: str, chat_upstream: str | None = None, **kwargs: Any
    ) -> None:
        self.gateway = ModelGateway(GatewayConfig(chat_upstream, messages_upstream))
        self._container_id: str | None = None
        self._public_networks: dict[str, dict[str, Any]] = {}
        self._network_lock = asyncio.Lock()
        self._network_history: list[dict[str, Any]] = []
        super().__init__(*args, **kwargs)
        if self._is_windows_container or self._uses_compose:
            raise ValueError("本地隔离仅支持无自定义 Compose 的单个 Linux 容器")

    @staticmethod
    def _requires_egress_control(
        *, startup_network_policy: NetworkPolicy, phase_network_policies: Sequence[NetworkPolicy]
    ) -> bool:
        # 整个原生 nft 分支被本类的隔离桥实现替代，不能降级到 public 继续运行。
        return False

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            disable_internet=True,
            network_allowlist=True,
            network_allowlist_hostnames=True,
            dynamic_network_policy=True,
            mounted=True,
        )

    def validate_network_policy_support(self, network_policy: NetworkPolicy | None = None) -> None:
        policy = network_policy or self.network_policy
        if policy.network_mode == NetworkMode.ALLOWLIST:
            if set(policy.allowed_hosts) != {GATEWAY_HOST}:
                raise ValueError(
                    "本地网关仅允许 saya-model-gateway 固定 API 集合，不支持域名白名单"
                )

    async def start(self, force_build: bool) -> None:
        await super().start(force_build)
        try:
            result = await self._run_docker_compose_command(["ps", "-q", "main"])
            self._container_id = (result.stdout or "").strip()
            if re.fullmatch(r"[0-9a-f]{12,64}", self._container_id) is None:
                raise RuntimeError("无法确定 Harbor 主容器的唯一身份")
            state = json.loads(await docker("inspect", self._container_id))[0]
            await self._save_runtime_record(state)
            self._public_networks = state["NetworkSettings"]["Networks"]
            if len(self._public_networks) != 1:
                raise ValueError("本地隔离要求 Harbor 主容器只有一个初始桥接网络")
            original = next(iter(self._public_networks))
            network = json.loads(await docker("network", "inspect", original))[0]
            if network["Driver"] != "bridge" or network["Internal"]:
                raise ValueError("Harbor 初始网络不是标准公开桥接网络")
            await self.gateway.start(original)
            await self._apply_network_policy(self.network_policy)
        except BaseException:
            await self.stop(delete=True)
            raise

    async def _save_runtime_record(self, state: dict[str, Any]) -> None:
        """所有 Agent 共用的只读证据：不改变网络，也不复制容器 Env。"""
        path = self.trial_paths.trial_dir / "runtime.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            host, config = state.get("HostConfig", {}), state.get("Config", {})
            image = json.loads(await docker("image", "inspect", state["Image"]))[0]
            cgroup_text = await docker(
                "exec",
                str(self._container_id),
                "sh",
                "-c",
                "for name in cpu.max memory.max memory.swap.max; do "
                'if [ -r "/sys/fs/cgroup/$name" ]; then '
                'printf "%s=" "$name"; cat "/sys/fs/cgroup/$name"; fi; done',
                timeout=10,
            )
            cgroup = {
                name: value
                for line in cgroup_text.splitlines()
                if (parts := line.partition("="))[1]
                and (name := parts[0]) in {"cpu.max", "memory.max", "memory.swap.max"}
                and (value := parts[2])
            }
            record = {
                "schema_version": 1,
                "available": True,
                "container_id": self._container_id,
                "image_reference": config.get("Image"),
                "image_id": state["Image"],
                "repo_digests": image.get("RepoDigests", []),
                "architecture": image.get("Architecture"),
                "os": image.get("Os"),
                "working_directory": config.get("WorkingDir"),
                "requested": {
                    key: getattr(self.task_env_config, key, None)
                    for key in ("cpus", "memory_mb", "storage_mb", "docker_image")
                },
                "docker_limits": {
                    key: host.get(key)
                    for key in (
                        "NanoCpus",
                        "CpuPeriod",
                        "CpuQuota",
                        "Memory",
                        "MemorySwap",
                        "StorageOpt",
                    )
                },
                "cgroup_v2": cgroup or None,
                "storage_hard_limit_supported": False,
                "scope": "main container only; model gateway has separate CPU and memory limits",
            }
        except Exception as exc:
            record = {"schema_version": 1, "available": False, "error_type": type(exc).__name__}
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    async def _attached_networks(self) -> dict[str, Any]:
        if self._container_id is None:
            raise RuntimeError("网络策略只能在主容器启动后应用")
        state = json.loads(await docker("inspect", self._container_id))[0]
        return dict(state["NetworkSettings"]["Networks"])

    async def _apply_network_policy(self, network_policy: NetworkPolicy) -> None:
        self.validate_network_policy_support(network_policy)
        async with self._network_lock:
            if self._container_id is None:
                raise RuntimeError("不能对未启动的主容器切换网络")
            mode = network_policy.network_mode
            if mode == NetworkMode.PUBLIC:
                desired = set(self._public_networks)
            elif mode == NetworkMode.ALLOWLIST:
                desired = {self.gateway.network}
            else:
                desired = set()
            try:
                attached = await self._attached_networks()
                # 先移除不允许的路径，再增加新路径；失败时停止容器，绝不公开联网继续执行。
                for name in set(attached) - desired:
                    await docker("network", "disconnect", name, self._container_id)
                for name in desired - set(attached):
                    arguments = ["network", "connect"]
                    if name in self._public_networks:
                        for alias in self._public_networks[name].get("Aliases") or []:
                            arguments.extend(("--alias", alias))
                    await docker(*arguments, name, self._container_id)
                current = await self._attached_networks()
                if set(current) != desired:
                    raise RuntimeError("Docker 实际网络与声明的阶段策略不符")
                self._network_history.append({"mode": mode.value, "attached": sorted(current)})
                self._save_network_record()
            except BaseException:
                await docker("stop", "--time", "1", self._container_id, check=False)
                raise

    def _save_network_record(self) -> None:
        path = self.trial_paths.trial_dir / "network-isolation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protocol": "local Docker isolated bridge + fixed nginx model gateway",
                    "official_modal_equivalence_claimed": False,
                    "gateway_image": NGINX_IMAGE,
                    "gateway_config_sha256": hashlib.sha256(
                        self.gateway.config_text.encode()
                    ).hexdigest(),
                    "gateway_container": self.gateway.container,
                    "isolated_network": self.gateway.network,
                    "cleanup_errors": self.gateway.cleanup_errors,
                    "gateway_startup_log": self.gateway.startup_log,
                    "history": self._network_history,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    async def stop(self, delete: bool) -> None:
        cleanup_failed = False
        try:
            try:
                if self._container_id is not None:
                    try:
                        attached = await self._attached_networks()
                    except (RuntimeError, ValueError):
                        self.logger.warning("清理网络时主容器已不可查询，继续清理独立网关")
                    else:
                        if self.gateway.network in attached:
                            await docker(
                                "network",
                                "disconnect",
                                self.gateway.network,
                                self._container_id,
                            )
            finally:
                try:
                    await self.gateway.close()
                except Exception:
                    # 原生 stop 移除主容器后，再尝试回收可能仍有端点占用的内部网。
                    cleanup_failed = True
        finally:
            try:
                await super().stop(delete)
            finally:
                try:
                    if cleanup_failed:
                        await self.gateway.close()
                finally:
                    self._save_network_record()
