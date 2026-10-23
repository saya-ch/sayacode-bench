"""原生 install_only 配置与完整46收据门禁；单元替身不冒充容器验证。"""

from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest
from harbor.job import Job as NativeJob
from test_installation import Environment

from sayacode_bench import installation
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.network import GatewayConfig, nginx_config
from scripts import preflight_installations as script


def reference(path: Path) -> dict[str, str]:
    return installation.file_reference(path)


def runtime(index: int) -> dict[str, Any]:
    return {
        "available": True,
        "image_id": "sha256:" + f"{index:064x}",
        "repo_digests": [f"public/task-{index}@sha256:" + f"{index + 100:064x}"],
        "architecture": "amd64",
        "os": "linux",
        "requested": {
            "cpus": 1,
            "memory_mb": 4096,
            "storage_mb": 10240,
            "docker_image": f"public/task-{index}:fixed",
        },
        "docker_limits": {
            "NanoCpus": 1000000000,
            "CpuPeriod": 0,
            "CpuQuota": 0,
            "Memory": 4294967296,
            "MemorySwap": 8589934592,
            "StorageOpt": None,
        },
        "cgroup_v2": {
            "cpu.max": "100000 100000",
            "memory.max": "4294967296",
            "memory.swap.max": "4294967296",
        },
        "storage_hard_limit_supported": False,
    }


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: Any) -> SimpleNamespace:
    root = tmp_path / "bundle"
    inputs_dir = root / "inputs/restart-v2"
    inputs_dir.mkdir(parents=True)
    cohort = {"ImageOS": "ubuntu24", "ImageVersion": "frozen", "RUNNER_ARCH": "X64"}
    cases = []
    for index in range(1, 47):
        identity = runtime(index)
        task = {
            "benchmark": "swe-bench-pro-v2" if index <= 32 else "terminal-bench-2.1",
            "task_id": f"task-{index}",
            "revision": "fixed",
            "agent": {"timeout_sec": 120, "user": "agent"},
            "environment": {**identity["requested"], "build_timeout_sec": 600},
        }
        cases.append(
            {
                "benchmark": task["benchmark"],
                "task_id": task["task_id"],
                "task": task,
                "runtime_identity": identity,
                "immutable_image": identity["repo_digests"][0],
                "host_cohort": cohort,
            }
        )
    originals = {}
    for name, content in (
        ("product.whl", b"wheel"),
        ("requirements.txt", b"requirements"),
        ("swe.tar.gz", b"qualification"),
        ("terminal.tar.gz", b"qualification"),
    ):
        path = inputs_dir / name
        path.write_bytes(content)
        originals[name] = reference(path)
    profile = inputs_dir / "profile.json"
    write_json(profile, {"model_id": "DeepSeek-V4.1-Flash", "protocol": "anthropic_messages"})
    variants = {}
    for name in ("baseline", "diagnostic", "focused"):
        path = inputs_dir / f"{name}.json"
        write_json(path, {"id": name, "profile_overrides": {}, "team_enabled": True})
        variants[name] = reference(path)
    source = "a" * 40
    inputs = {
        "schema_version": 1,
        "source_sha": source,
        "bundle_root": str(root),
        "product_wheel": originals["product.whl"],
        "requirements": originals["requirements.txt"],
        "profile": reference(profile),
        "variants": variants,
        "qualifications": [
            {"benchmark": name, "archive": originals[file]}
            for name, file in (
                ("swe-bench-pro-v2", "swe.tar.gz"),
                ("terminal-bench-2.1", "terminal.tar.gz"),
            )
        ],
    }
    inputs_path = inputs_dir / "installation-inputs.json"
    write_json(inputs_path, inputs)
    original_read = installation.read_json

    def configured_read(path: Path) -> dict[str, Any]:
        if path == script.ROOT / "reproduction/identity.json":
            return {
                "production_wheel_sha256": originals["product.whl"]["sha256"],
                "requirements_sha256": originals["requirements.txt"]["sha256"],
            }
        return original_read(path)

    monkeypatch.setattr(installation, "read_json", configured_read)
    monkeypatch.setattr(
        installation, "qualified_installation_tasks", lambda _: copy.deepcopy(cases)
    )
    monkeypatch.setattr(script, "qualified_installation_tasks", lambda _: copy.deepcopy(cases))
    monkeypatch.setattr(script, "require_hosted_runner", lambda: None)
    monkeypatch.setattr(script, "verify_source", lambda _: None)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    for name in (
        "STUDY_CONNECTION_KEYS_JSON",
        "SAYACODE_STUDY_CONNECTION_KEYS_JSON",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "SILICONFLOW_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(script.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))
    source_identity = {"implementation": {"test": "frozen"}, "source_files": {"script": "frozen"}}
    monkeypatch.setattr(installation, "source_identity", lambda: source_identity)
    monkeypatch.setattr(script, "source_identity", lambda: source_identity)
    preparation, probe = root / "runner.json", root / "probe.json"
    write_json(
        preparation,
        {
            "passed": True,
            "repository": "saya-ch/sayacode-bench-runs",
            "runner_image": cohort,
            "script_sha256": file_sha256(script.ROOT / "scripts/prepare_cloud_runner.py"),
        },
    )
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "cleanup_errors": [],
            "source_sha256": {
                "network.py": file_sha256(script.ROOT / "src/sayacode_bench/network.py"),
                "test_network.py": file_sha256(script.ROOT / "tests/test_network.py"),
            },
        },
    )
    state = SimpleNamespace(
        root=root,
        inputs=inputs,
        inputs_path=inputs_path,
        source=source,
        cases=cases,
        preparation=preparation,
        probe=probe,
        jobs=[],
        fail=False,
        source_identity=source_identity,
    )

    class RecordingJob:
        def __init__(self, config: Any) -> None:
            raise ValueError("Use await Job.create(config)")

        @classmethod
        async def create(cls, config: Any) -> RecordingJob:
            job = object.__new__(cls)
            job.config = config
            state.jobs.append(config)
            return job

        async def run(self) -> None:
            config = self.config
            assert config.install_only is True and config.verifier.disable is True
            assert config.n_attempts == config.n_concurrent_trials == 1
            assert config.retry.max_retries == 0
            assert config.agents[0].import_path == "sayacode_bench.adapter:SayacodeAgent"
            assert config.agents[0].model_name is None
            index = int(config.job_name.rsplit("-", 1)[1])
            job = config.jobs_dir / config.job_name
            trial = job / "preflight__native"
            evidence = trial / "agent/installation"
            environment = Environment()

            async def dependencies(*args: Any) -> None:
                return None

            bootstrap = await installation.prepare_uv_installer(
                environment,
                PurePosixPath("/installed-agent/sayacode/install-uv.sh"),
                evidence,
                dependencies,
            )
            await installation.verify_installed_runtime(
                environment,
                PurePosixPath("/installed-agent/sayacode"),
                evidence,
                bootstrap,
                wheel=Path(inputs["product_wheel"]["path"]),
                requirements=Path(inputs["requirements"]["path"]),
            )
            observed_runtime = runtime(index)
            # 真实环境记录的是实际启动的 digest，资格原件仍保留原 tag。
            observed_runtime["requested"]["docker_image"] = cases[index - 1]["immutable_image"]
            write_json(trial / "runtime.json", observed_runtime)
            write_json(
                trial / "result.json",
                {
                    "config": {
                        "install_only": True,
                        "agent": {
                            "import_path": "sayacode_bench.adapter:SayacodeAgent",
                            "model_name": None,
                        },
                    },
                    "agent_setup": {"started_at": "start", "finished_at": "end"},
                    "finished_at": "end",
                    "agent_execution": None,
                    "verifier": None,
                    "agent_result": None,
                    "verifier_result": None,
                    "exception_info": {"exception_type": "SetupFailed"} if state.fail else None,
                },
            )
            write_json(
                job / "result.json",
                {
                    "finished_at": "end",
                    "n_total_trials": 1,
                    "stats": {
                        "n_completed_trials": 1,
                        "n_errored_trials": int(state.fail),
                        "n_running_trials": 0,
                        "n_pending_trials": 0,
                        "n_retries": 0,
                    },
                },
            )

    monkeypatch.setattr(script, "Job", RecordingJob)
    return state


async def case(setup: SimpleNamespace, index: int) -> Path:
    output = setup.root / "installations/restart-v2" / f"case-{index:04d}"
    result = await script.run_case(
        setup.inputs_path, setup.source, index, output, setup.preparation, setup.probe
    )
    assert result["passed"] is (not setup.fail)
    return output / "case-receipt.json"


async def test_native_install_only_and_exclusive_case_output(setup: SimpleNamespace) -> None:
    path = await case(setup, 6)
    original = path.read_bytes()
    config = setup.jobs[0]
    assert str(config.tasks[0].path).endswith("synthetic-task")
    upstream = config.environment.kwargs["messages_upstream"]
    assert upstream == "http://127.0.0.1:9/v1/messages"
    gateway = nginx_config(GatewayConfig(chat_upstream=None, messages_upstream=upstream))
    assert "server 127.0.0.1:9 resolve;" in gateway
    assert "proxy_pass http://saya_messages/v1/messages;" in gateway
    assert setup.cases[5]["runtime_identity"]["requested"]["docker_image"].endswith(":fixed")
    assert "api_key" not in read_json(Path(setup.inputs["profile"]["path"]))
    with pytest.raises(FileExistsError):
        await case(setup, 6)
    assert len(setup.jobs) == 1 and path.read_bytes() == original


async def test_real_harbor_create_reaches_run_boundary_without_docker(
    setup: SimpleNamespace, monkeypatch: Any
) -> None:
    reached = []

    async def boundary(job: NativeJob) -> None:
        reached.append(job)
        # 官方 create 已完整返回；不进入 run 的容器或模型执行。
        job._close_logger_handlers()
        raise RuntimeError("native-run-boundary")

    monkeypatch.setattr(script, "Job", NativeJob)
    monkeypatch.setattr(NativeJob, "run", boundary)
    output = setup.root / "installations/restart-v2/case-0006"
    result = await script.run_case(
        setup.inputs_path, setup.source, 6, output, setup.preparation, setup.probe
    )
    assert len(reached) == 1
    config = reached[0].config
    assert config.install_only is True and config.verifier.disable is True
    assert config.n_attempts == config.n_concurrent_trials == 1
    assert config.retry.max_retries == 0
    assert config.agents[0].import_path == "sayacode_bench.adapter:SayacodeAgent"
    assert config.agents[0].model_name is None
    gateway = nginx_config(GatewayConfig(chat_upstream=None, **config.environment.kwargs))
    assert "server 127.0.0.1:9 resolve;" in gateway
    assert "proxy_pass http://saya_messages/v1/messages;" in gateway
    assert result["error_type"] == "RuntimeError"
    assert result["failure_message"] == "native-run-boundary"
    assert result["complete"] is False and result["passed"] is False


async def test_model_secret_blocks_before_native_job(
    setup: SimpleNamespace, monkeypatch: Any
) -> None:
    monkeypatch.setenv("STUDY_CONNECTION_KEYS_JSON", "do-not-output-this")
    with pytest.raises(ValueError, match="凭据"):
        await case(setup, 1)
    assert setup.jobs == []


async def test_native_failure_never_becomes_passed_case(setup: SimpleNamespace) -> None:
    setup.fail = True
    path = await case(setup, 1)
    result = read_json(path)
    assert result["passed"] is False and result["complete"] is False
    assert result["native"]["trial_result"]["sha256"]


async def test_partial_merge_never_reduces_46_denominator(setup: SimpleNamespace) -> None:
    path = await case(setup, 1)
    output = setup.root / "installations/restart-v2/preflight.json"
    result = script.merge_cases(setup.inputs_path, setup.source, [path], output)
    assert result["passed"] is False and result["complete"] is False
    assert result["missing_indices"] == list(range(2, 47))
    with pytest.raises(ValueError, match="46"):
        installation.validate_installation_preflight(reference(output))


async def test_complete_gate_reopens_all_46_and_supports_phase_subsets(
    setup: SimpleNamespace,
) -> None:
    paths = [await case(setup, index) for index in range(1, 47)]
    output = setup.root / "installations/restart-v2/preflight.json"
    result = script.merge_cases(setup.inputs_path, setup.source, paths, output)
    assert result["passed"] is True
    artifacts = script._artifacts(setup.inputs)
    artifacts["variants"] = {"baseline": artifacts["variants"]["baseline"]}
    for selected in (setup.cases[:8], setup.cases[8:32], setup.cases[34:]):
        checked = installation.validate_installation_preflight(
            reference(output),
            tasks=[c["task"] for c in selected],
            artifacts=artifacts,
            implementation=setup.source_identity["implementation"],
        )
        assert checked["coverage"] == {"swe-bench-pro-v2": 32, "terminal-bench-2.1": 14}
    damaged = read_json(paths[45])
    raw = Path(damaged["native"]["trial_result"]["path"])
    value = read_json(raw)
    value["agent_execution"] = {"started_at": "unexpected-model-stage"}
    write_json(raw, value)
    damaged["native"]["trial_result"] = reference(raw)
    write_json(paths[45], damaged)
    result["cases"][45] = reference(paths[45])
    write_json(output, result)
    # 即使阶段只选dev8，最后一个Terminal原件有问题也不能放行。
    with pytest.raises(ValueError, match="install_only"):
        installation.validate_installation_preflight(
            reference(output), tasks=[c["task"] for c in setup.cases[:8]]
        )


async def test_changed_output_or_runtime_cannot_be_covered_by_pass_flag(
    setup: SimpleNamespace,
) -> None:
    path = await case(setup, 1)
    value = read_json(path)
    installed = read_json(Path(value["native"]["installation"]["path"]))
    stdout = Path(installed["checks"][1]["stdout_file"]["path"])
    stdout.write_text("different product version", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        installation.validate_installation_case_native(
            value, path.parent, setup.cases[0], script._artifacts(setup.inputs)
        )


@pytest.mark.parametrize("change", ["unpinned_request", "different_image", "different_memory"])
async def test_digest_alias_does_not_relax_actual_identity_or_resources(
    setup: SimpleNamespace, change: str
) -> None:
    original = copy.deepcopy(setup.cases[0]["runtime_identity"])
    path = await case(setup, 1)
    value = read_json(path)
    runtime_path = Path(value["native"]["runtime"]["path"])
    observed = read_json(runtime_path)
    if change == "unpinned_request":
        observed["requested"]["docker_image"] = original["requested"]["docker_image"]
    elif change == "different_image":
        observed["image_id"] = "sha256:" + "f" * 64
    else:
        observed["docker_limits"]["Memory"] += 1024
    write_json(runtime_path, observed)
    value["native"]["runtime"] = reference(runtime_path)
    with pytest.raises(ValueError, match="镜像或官方资源"):
        installation.validate_installation_case_native(
            value, path.parent, setup.cases[0], script._artifacts(setup.inputs)
        )
    assert setup.cases[0]["runtime_identity"] == original


async def test_cohort_failure_keeps_attempt_but_does_not_start_job(setup: SimpleNamespace) -> None:
    value = read_json(setup.preparation)
    value["runner_image"]["ImageVersion"] = "drifted"
    write_json(setup.preparation, value)
    output = setup.root / "installations/restart-v2/case-0001"
    result = await script.run_case(
        setup.inputs_path, setup.source, 1, output, setup.preparation, setup.probe
    )
    assert result["passed"] is False and setup.jobs == []
    assert (output / "attempt.json").is_file()
