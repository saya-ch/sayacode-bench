"""网关配置、阶段切换与可选择执行的真实 Docker 隔离探针。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.trial.paths import TrialPaths

from sayacode_bench import network
from sayacode_bench.network import (
    GATEWAY_BASE_URL,
    GATEWAY_HOST,
    GatewayConfig,
    IsolatedDockerEnvironment,
    nginx_config,
)

CONFIG = GatewayConfig(
    "http://host.docker.internal:8787/v1/chat/completions",
    "http://host.docker.internal:8787/anthropic/v1/messages",
)


def test_nginx_has_only_fixed_post_routes_and_no_credentials() -> None:
    config = nginx_config(CONFIG)
    assert config.count("proxy_pass ") == 2
    assert "location = /v1/chat/completions" in config
    assert "location = /v1/messages" in config
    assert config.count("if ($request_method != POST)") == 2
    assert "location / { return 404; }" in config
    assert "proxy_next_upstream off" in config
    assert "proxy_buffering off" in config
    assert "proxy_ssl_verify on" in config
    assert "Authorization" not in config
    assert "api_key" not in config
    assert "proxy_pass $" not in config
    assert all(f"{kind}_temp_path /tmp/" in config for kind in ("fastcgi", "uwsgi", "scgi"))


def test_messages_only_job_does_not_expose_chat_route() -> None:
    config = nginx_config(GatewayConfig(None, CONFIG.messages_upstream))
    assert "location = /v1/messages" in config
    assert "location = /v1/chat/completions" not in config
    assert config.count("proxy_pass ") == 1


def test_harbor_extra_agent_host_preserves_public_setup_and_verifier() -> None:
    from harbor.models.task.config import TaskConfig, VerifierEnvironmentMode
    from harbor.models.trial.config import AgentConfig
    from harbor.models.trial.config import EnvironmentConfig as TrialEnvironmentConfig
    from harbor.trial.network_policy import resolve_trial_network_plan

    task = TaskConfig.model_validate(
        {"agent": {"network_mode": "no-network"}, "environment": {"network_mode": "public"}}
    )
    plan = resolve_trial_network_plan(
        task,
        AgentConfig(name="nop", extra_allowed_hosts=[GATEWAY_HOST]),
        TrialEnvironmentConfig(type="docker"),
        None,
        verifier_mode=VerifierEnvironmentMode.SHARED,
    )
    assert plan.agent_env_baseline.network_mode == NetworkMode.PUBLIC
    assert plan.agent_phase.network_mode == NetworkMode.ALLOWLIST
    assert plan.agent_phase.allowed_hosts == [GATEWAY_HOST]
    assert plan.verifier_phase.network_mode == NetworkMode.PUBLIC


@pytest.mark.parametrize(
    "value",
    [
        "http://secret@example.com/v1/chat/completions",
        "http://example.com/v1/chat/completions?api_key=secret",
        "http://example.com/v1/chat/completions#secret",
        "http://example.com/../v1/chat/completions",
        "file:///v1/chat/completions",
        "http://example.com/other-route",
        "http://example.com/v1/chat/completions;evil",
    ],
)
def test_gateway_rejects_credentials_or_nginx_injection(value: str) -> None:
    with pytest.raises(ValueError):
        nginx_config(GatewayConfig(value, CONFIG.messages_upstream))


def _environment(tmp_path: Path) -> IsolatedDockerEnvironment:
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "Dockerfile").write_text("FROM example/probe:fixed\n", encoding="utf-8")
    return IsolatedDockerEnvironment(
        environment_dir=environment_dir,
        environment_name="network-probe",
        session_id=f"network-probe-{uuid.uuid4().hex[:8]}",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=EnvironmentConfig(
            docker_image="example/probe:fixed", cpus=1, memory_mb=256
        ),
        chat_upstream=CONFIG.chat_upstream,
        messages_upstream=CONFIG.messages_upstream,
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),
        phase_network_policies=[NetworkPolicy(network_mode=NetworkMode.NO_NETWORK)],
    )


def test_custom_environment_does_not_call_native_nft_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden() -> bool:
        raise AssertionError("不得进入原生 nft 模式")

    monkeypatch.setattr(network.DockerEnvironment, "_egress_control_kernel_support", forbidden)
    environment = _environment(tmp_path)
    assert not environment._enable_egress_control
    assert environment.capabilities.dynamic_network_policy
    assert environment.capabilities.network_allowlist
    assert environment.resource_capabilities().memory_limit


def test_unknown_allowlist_host_is_rejected(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    with pytest.raises(ValueError, match="仅允许"):
        environment.validate_network_policy_support(
            NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["example.com"])
        )


def test_raw_upstream_hostname_is_not_a_gateway_grant(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    with pytest.raises(ValueError, match="固定 API 集合"):
        environment.validate_network_policy_support(
            NetworkPolicy(
                network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["host.docker.internal"]
            )
        )


async def test_gateway_cleanup_failure_is_visible_and_retains_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = network.ModelGateway(CONFIG)
    gateway._temporary = tmp_path / "config"
    gateway._temporary.mkdir()
    (gateway._temporary / "nginx.conf").write_text(gateway.config_text, encoding="utf-8")
    calls = []

    async def fake_docker(*arguments: str, **kwargs: Any) -> str:
        calls.append(arguments)
        if "ls" in arguments:
            return "resource-id"
        raise RuntimeError("engine error")

    monkeypatch.setattr(network, "docker", fake_docker)
    with pytest.raises(RuntimeError, match="网络清理未确认"):
        await gateway.close()
    assert len(gateway.cleanup_errors) == 2
    assert (tmp_path / "config" / "nginx.conf").exists()
    assert any(call[:2] == ("network", "rm") for call in calls)

    async def absent(*arguments: str, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(network, "docker", absent)
    await gateway.close()
    await gateway.close()
    assert gateway.cleanup_errors == []
    assert not (tmp_path / "config").exists()


async def test_phase_network_switch_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    environment._container_id = "a" * 64
    environment._public_networks = {"original": {"Aliases": ["main"]}}
    attached = {"original": {}}
    calls: list[tuple[str, ...]] = []

    async def fake_docker(*arguments: str, **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments[0] == "inspect":
            return json.dumps([{"NetworkSettings": {"Networks": attached}}])
        if arguments[:2] == ("network", "disconnect"):
            attached.pop(arguments[2])
        if arguments[:2] == ("network", "connect"):
            attached[arguments[-2]] = {}
        return ""

    monkeypatch.setattr(network, "docker", fake_docker)
    policy = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[GATEWAY_HOST])
    await environment.set_network_policy(policy)
    assert set(attached) == {environment.gateway.network}
    disconnect = next(i for i, call in enumerate(calls) if call[:2] == ("network", "disconnect"))
    connect = next(i for i, call in enumerate(calls) if call[:2] == ("network", "connect"))
    assert disconnect < connect
    await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.NO_NETWORK))
    assert not attached
    await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.PUBLIC))
    assert set(attached) == {"original"}
    record = json.loads((tmp_path / "trial" / "network-isolation.json").read_text(encoding="utf-8"))
    assert [item["mode"] for item in record["history"]] == ["allowlist", "no-network", "public"]
    assert record["official_modal_equivalence_claimed"] is False


async def test_failed_connection_stops_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = _environment(tmp_path)
    environment._container_id = "a" * 64
    environment._public_networks = {"original": {}}
    calls = []

    async def fake_docker(*arguments: str, **kwargs: Any) -> str:
        calls.append(arguments)
        if arguments[0] == "inspect":
            return json.dumps([{"NetworkSettings": {"Networks": {"original": {}}}}])
        if arguments[:2] == ("network", "connect"):
            raise RuntimeError("connection failed")
        return ""

    monkeypatch.setattr(network, "docker", fake_docker)
    with pytest.raises(RuntimeError, match="connection failed"):
        await environment.set_network_policy(
            NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[GATEWAY_HOST])
        )
    assert any(call[0] == "stop" for call in calls)
    assert environment.network_policy.network_mode == NetworkMode.PUBLIC


class _MockAPI(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._respond()

    def _respond(self) -> None:
        body = json.dumps({"source": "unpaid-local-mock", "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


_PROBE = r"""
import http.client,json,pathlib,socket,urllib.error,urllib.request
config=json.loads(CONFIG_JSON)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(url,method='GET'):
    try:
        data=b'{}' if method=='POST' else None
        r=opener.open(urllib.request.Request(url,data=data,method=method),timeout=4)
        return {'reachable':True,'status':r.status,'body':r.read(1000).decode()}
    except urllib.error.HTTPError as e:return {'reachable':True,'status':e.code}
    except (OSError,urllib.error.URLError) as e:return {'reachable':False,'error_type':type(e).__name__}
def tcp(host,port):
    try:
        with socket.create_connection((host,port),timeout=3):pass
        return True
    except OSError:return False
result={}
if config['phase']=='none':
    result['gateway']=request(config['gateway']+'/v1/messages','POST')
    result['host_mock']=request(config['mock'])
    result['public_ip_tcp']=tcp('1.1.1.1',443)
elif config['phase']=='public':
    result['host_mock']=request(config['mock'])
    result['host_ip']=socket.gethostbyname('host.docker.internal')
    result['host_ip_tcp']=tcp(result['host_ip'],config['mock_port'])
    result['bridge_host_tcp']=tcp(config['bridge_host'],config['mock_port'])
    try:result['public_domain_resolved']=bool(socket.gethostbyname('example.com'))
    except OSError as e:
        result['public_domain_resolved']=False
        result['public_dns_error_type']=type(e).__name__
    result['public_ip_tcp']=tcp('1.1.1.1',443)
else:
    base=config['gateway']
    result['chat']=request(base+'/v1/chat/completions','POST')
    result['messages']=request(base+'/v1/messages','POST')
    result['get_model']=request(base+'/v1/chat/completions')
    result['other_path']=request(base+'/v1/models')
    result['query']=request(base+'/v1/chat/completions?target=evil','POST')
    result['reference_path']=request(base+'/solution/solve.sh')
    result['reference_files_present']=any(pathlib.Path(p).exists() for p in ['/solution','/tests'])
    result['public_domain']=request('https://example.com')
    result['public_ip_tcp']=tcp('1.1.1.1',443)
    result['host_mock']=request(config['mock'])
    result['bridge_host_tcp']=tcp(config['bridge_host'],config['mock_port'])
    try:result['public_domain_resolved']=bool(socket.gethostbyname('example.com'))
    except OSError as e:
        result['public_domain_resolved']=False
        result['public_dns_error_type']=type(e).__name__
    result['host_ip_tcp']=tcp(config['host_ip'],config['mock_port'])
    try:result['host_name_resolved']=bool(socket.gethostbyname('host.docker.internal'))
    except OSError as e:
        result['host_name_resolved']=False
        result['host_dns_error_type']=type(e).__name__
    conn=http.client.HTTPConnection('saya-model-gateway',8080,timeout=4)
    try:
        conn.request('CONNECT','example.com:443')
        result['connect_status']=conn.getresponse().status
    finally:conn.close()
print(json.dumps(result))
"""


@pytest.mark.skipif(
    os.environ.get("SAYACODE_BENCH_DOCKER_TESTS") != "1", reason="显式启用真实 Docker 离线网络探针"
)
async def test_real_docker_network_isolation(tmp_path: Path) -> None:
    """只访问本地 mock 与公共连通性探针，不调用任何付费模型。"""

    image = (
        "python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b"
    )
    server = ThreadingHTTPServer(("0.0.0.0", 0), _MockAPI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    directory = tmp_path / "environment"
    directory.mkdir()
    (directory / "Dockerfile").write_text(f"FROM {image}\n", encoding="utf-8")
    paths = TrialPaths(tmp_path / "trial")
    paths.mkdir()
    environment = IsolatedDockerEnvironment(
        environment_dir=directory,
        environment_name="unpaid-network-probe",
        session_id=f"saya-unpaid-probe-{uuid.uuid4().hex[:12]}",
        trial_paths=paths,
        task_env_config=EnvironmentConfig(
            docker_image=image, cpus=1, memory_mb=256, storage_mb=1024
        ),
        chat_upstream=f"http://host.docker.internal:{port}/v1/chat/completions",
        messages_upstream=f"http://host.docker.internal:{port}/v1/messages",
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),
        phase_network_policies=[
            NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[GATEWAY_HOST])
        ],
    )
    evidence: dict[str, Any] = {"paid_model_requests": 0, "passed": False}

    async def probe(phase: str) -> dict[str, Any]:
        config = {
            "phase": phase,
            "mock": f"http://host.docker.internal:{port}/health",
            "mock_port": port,
            "gateway": GATEWAY_BASE_URL,
            "bridge_host": next(iter(environment._public_networks.values()))["Gateway"],
            "host_ip": evidence.get("setup", {}).get("host_ip"),
        }
        script = "CONFIG_JSON=" + repr(json.dumps(config)) + "\n" + _PROBE
        result = await environment.exec("python -c " + shlex.quote(script), timeout_sec=90)
        assert result.return_code == 0, result.stderr
        return json.loads(result.stdout)

    try:
        await environment.start(force_build=False)
        runtime = json.loads((paths.trial_dir / "runtime.json").read_text(encoding="utf-8"))
        assert runtime["available"] is True
        assert runtime["image_id"].startswith("sha256:")
        assert runtime["docker_limits"]["NanoCpus"] == 1000000000
        assert runtime["docker_limits"]["Memory"] == 256 * 1024**2
        assert runtime["storage_hard_limit_supported"] is False
        evidence["runtime"] = runtime
        public = evidence["setup"] = await probe("public")
        assert public["host_mock"]["status"] == 200
        assert public["host_ip_tcp"] is True
        assert public["public_ip_tcp"] is True
        await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.NO_NETWORK))
        offline = evidence["no_network"] = await probe("none")
        assert offline["gateway"]["reachable"] is False
        assert offline["host_mock"]["reachable"] is False
        assert offline["public_ip_tcp"] is False
        await environment.set_network_policy(
            NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=[GATEWAY_HOST])
        )
        restricted = evidence["agent"] = await probe("restricted")
        assert restricted["chat"]["status"] == 200
        assert restricted["messages"]["status"] == 200
        assert restricted["get_model"]["status"] == 405
        assert restricted["other_path"]["status"] == 404
        assert restricted["query"]["status"] == 400
        assert restricted["reference_path"]["status"] == 404
        assert restricted["reference_files_present"] is False
        assert restricted["public_domain"]["reachable"] is False
        assert restricted["public_ip_tcp"] is False
        assert restricted["host_mock"]["reachable"] is False
        assert restricted["host_ip_tcp"] is False
        assert restricted["bridge_host_tcp"] is False
        assert restricted["connect_status"] in (400, 403, 405)
        await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.PUBLIC))
        verifier = evidence["verifier"] = await probe("public")
        assert verifier["host_mock"]["status"] == 200
        assert verifier["public_ip_tcp"] is True
        evidence["passed"] = True
    finally:
        evidence["history"] = environment._network_history
        evidence["gateway_startup_log"] = environment.gateway.startup_log
        evidence["gateway_runtime_log"] = await network.docker(
            "logs", environment.gateway.container, check=False, include_stderr=True
        )
        try:
            await environment.stop(delete=True)
            assert not await network.docker(
                "container",
                "ls",
                "--all",
                "--filter",
                f"name=^/{environment.gateway.container}$",
                "--format",
                "{{.ID}}",
            )
            assert not await network.docker(
                "network",
                "ls",
                "--filter",
                f"name=^{environment.gateway.network}$",
                "--format",
                "{{.ID}}",
            )
            evidence["cleanup_complete"] = True
        except BaseException as error:
            evidence["cleanup_complete"] = False
            evidence["cleanup_error_type"] = type(error).__name__
            evidence["passed"] = False
            raise
        finally:
            evidence["cleanup_errors"] = environment.gateway.cleanup_errors
            evidence["gateway_container"] = environment.gateway.container
            evidence["isolated_network"] = environment.gateway.network
            evidence["source_sha256"] = {
                "network.py": hashlib.sha256(Path(network.__file__).read_bytes()).hexdigest(),
                "test_network.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
            evidence["harbor_version"] = version("harbor")
            evidence["network_sha256"] = evidence["source_sha256"]["network.py"]
            evidence["nginx_image"] = network.NGINX_IMAGE
            output = os.environ.get("SAYACODE_BENCH_PROBE_OUTPUT")
            if output:
                output_path = Path(output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            server.shutdown()
            server.server_close()
            await asyncio.to_thread(thread.join, 5)
