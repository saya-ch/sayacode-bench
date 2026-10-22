"""完整离线用户序列：冻结输入、官方 Job 工件、全新重判、恢复与中止。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.verifier.result import VerifierResult

from sayacode_bench import cli, execution, study
from sayacode_bench.artifacts import file_sha256, read_json, write_json
from sayacode_bench.connections import CANONICAL_MODEL
from sayacode_bench.sources import SOURCES, SourceSnapshot, tree_digest


@pytest.fixture
def experiment(tmp_path: Path, monkeypatch: Any) -> Any:
    source = tmp_path / "cache" / "snapshot"
    spec = SOURCES["swe-bench-pro-v2"]
    task = source / spec.tasks_path / "instance_demo"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('version="1.0"\n', encoding="utf-8")
    (task / "instruction.md").write_text("Fix the specified behavior.\n", encoding="utf-8")
    tooling = source / "v2" / "tooling"
    tooling.mkdir(exist_ok=True)
    (tooling / "patch_replay.py").write_text("class PatchReplayAgent: pass\n", encoding="utf-8")
    snapshot = SourceSnapshot(spec, source, "source-archive", 0)
    monkeypatch.setattr(study, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(cli, "fetch_source", lambda *args: snapshot)
    monkeypatch.setattr(
        study.shutil, "disk_usage", lambda *args: SimpleNamespace(free=100 * 1024**3)
    )
    artifact = tmp_path / "artifacts"
    artifact.mkdir()
    wheel, requirements = artifact / "product.whl", artifact / "requirements.txt"
    wheel.write_bytes(b"frozen-wheel")
    requirements.write_text("dependency==1\n", encoding="utf-8")
    variants = {}
    for name in ("baseline", "candidate"):
        path = tmp_path / f"{name}.json"
        write_json(path, {"id": name, "team_enabled": True})
        variants[name] = path
    private = tmp_path / "private"
    private.mkdir()
    profile_path = private / "connection.json"
    profile = {
        "name": "fixture",
        "protocol": "anthropic_messages",
        "base_url": "https://model.invalid/v1",
        "api_key": "private-never-publish",
        "model_id": "DeepSeek-V4.1-Flash",
        "context_length": 65536,
        "max_output_tokens": 8192,
    }
    write_json(profile_path, profile)
    row = {
        "task_id": task.name,
        "benchmark": spec.name,
        "revision": spec.revision,
        "repository": "fixture/repo",
        "instruction_sha256": file_sha256(task / "instruction.md"),
        "config_sha256": file_sha256(task / "task.toml"),
        "task_tree_sha256": tree_digest(task),
    }
    manifest = {
        "phase": "calibration",
        "frozen": True,
        "canonical_model": CANONICAL_MODEL,
        "benchmark": spec.name,
        "revision": spec.revision,
        "seed": "offline-sequence",
        "tasks": [row],
        "configurations": list(variants),
        "baseline": "baseline",
        "candidate": None,
        "repeats": 1,
        "connections": ["local"],
        "connection_profiles": {
            "local": {key: value for key, value in profile.items() if key != "api_key"}
        },
        "reported_token_limit": 100000,
        "validity_issues": [],
    }
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    prior = sys.modules.pop("patch_replay", None)
    bundle = SimpleNamespace(
        root=tmp_path,
        source=source,
        task=task,
        tooling=tooling,
        cache=tmp_path / "cache",
        wheel=wheel,
        requirements=requirements,
        variants=variants,
        private=private,
        connections={"local": profile_path},
        manifest=manifest,
        manifest_path=manifest_path,
        output=tmp_path / "results",
    )
    yield bundle
    sys.modules.pop("patch_replay", None)
    if prior is not None:
        sys.modules["patch_replay"] = prior


def install_jobs(monkeypatch: Any) -> list[Any]:
    calls = []

    async def create(config: Any) -> Any:
        calls.append(config)

        async def run() -> Any:
            task_id = config.tasks[0].path.name
            name = task_id + "__offline"
            path = config.jobs_dir / config.job_name / name
            write_json(path / "result.json", {"task_name": task_id})
            write_json(
                path / "runtime.json",
                {
                    "available": True,
                    "image_id": "sha256:" + "a" * 64,
                    "architecture": "amd64",
                    "os": "linux",
                    "docker_limits": {"Memory": 4096},
                },
            )
            write_json(
                config.jobs_dir / config.job_name / "result.json", {"job_name": config.job_name}
            )
            agent = config.agents[0]
            replay = agent.import_path == "patch_replay:PatchReplayAgent"
            reward = 1 if replay or agent.name == "oracle" else 0
            if replay:
                source = Path(agent.kwargs["source_job"])
                raw = next(source.glob("instance_*/result.json"))
                patch = raw.parent / "agent" / "model.patch"
                write_json(path / "agent" / "replay.json", {"patch": str(patch), "apply_rc": 0})
            elif agent.import_path:
                write_json(
                    path / "agent" / "sayacode" / "result.json",
                    {
                        "status": "completed",
                        "task_count": 2,
                        "child_roles": ["planner", "reviewer"],
                        "usage": {
                            "model_calls": 1,
                            "reported_calls": 1,
                            "missing_usage_calls": 0,
                            "damaged_audit_lines": 0,
                            "input_tokens": 100,
                            "output_tokens": 10,
                        },
                    },
                )
                (path / "agent" / "model.patch").write_text(
                    "diff --git a/x b/x\n+fixed\n", encoding="utf-8"
                )
            now = datetime.now(UTC)
            trial = SimpleNamespace(
                task_name=task_id,
                trial_name=name,
                task_checksum="frozen-task",
                agent_result=AgentContext(),
                exception_info=None,
                verifier_result=VerifierResult.model_construct(rewards={"reward": reward}),
                started_at=now,
                finished_at=now + timedelta(seconds=2),
            )
            return SimpleNamespace(trial_results=[trial])

        return SimpleNamespace(run=run)

    monkeypatch.setattr(execution.Job, "create", create)
    return calls


def freeze_arguments(bundle: Any, gate: Path, probe: Path) -> argparse.Namespace:
    selection = bundle.root / "selection.json"
    write_json(selection, {"dev": bundle.manifest["tasks"], "holdout": []})
    return argparse.Namespace(
        phase="dev",
        selection=selection,
        sanity=gate,
        network_probe=probe,
        variant=[f"{name}={path}" for name, path in bundle.variants.items()],
        connection=[f"{name}={path}" for name, path in bundle.connections.items()],
        repeats=1,
        seed="offline",
        reported_token_limit=10000,
        wheel=bundle.wheel,
        requirements=bundle.requirements,
        output=bundle.root / "frozen-dev.json",
        candidate_lock=None,
    )


async def run_phase(bundle: Any) -> dict[str, Any]:
    return await study.run_phase(
        bundle.manifest_path,
        bundle.output,
        bundle.cache,
        bundle.wheel,
        bundle.requirements,
        bundle.variants,
        bundle.connections,
        bundle.private,
    )


async def test_complete_offline_phase_uses_original_job_and_pristine_replay_then_resumes(
    experiment: Any,
    monkeypatch: Any,
) -> None:
    calls = install_jobs(monkeypatch)
    result = await run_phase(experiment)
    assert len(calls) == 4
    assert (
        sum(config.agents[0].import_path == "patch_replay:PatchReplayAgent" for config in calls)
        == 2
    )
    records = [
        json.loads(line)
        for line in (experiment.output / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {(row["configuration"], row["repeat"]) for row in records} == {
        ("baseline", 1),
        ("candidate", 1),
    }
    for row in records:
        assert row["verification_kind"] == "pristine_replay"
        assert row["original_reward"] == 0 and row["replay_reward"] == 1
        assert row["success"] is True and row["verified"] is True
        assert row["input_tokens"] == 100 and row["output_tokens"] == 10
        assert Path(row["source_job"]).parent == experiment.output / "jobs"
        assert Path(row["replay_job_dir"]).parent == experiment.output / "replays"
    assert result["groups"]["baseline"]["successes"] == 1
    assert result["formal_comparison_eligible"] is False
    assert all(
        config.environment.kwargs["messages_upstream"] == "https://model.invalid/v1/messages"
        for config in calls
    )
    assert "private-never-publish" not in json.dumps(result)
    resumed = await run_phase(experiment)
    assert resumed == result and len(calls) == 4


async def test_user_sequence_sanity_freeze_run_pristine_replay_and_cli_report(
    experiment: Any,
    monkeypatch: Any,
) -> None:
    calls = install_jobs(monkeypatch)
    selection = experiment.root / "selection.json"
    write_json(selection, {"dev": experiment.manifest["tasks"], "holdout": []})
    sanity_output = experiment.root / "sanity"
    gate = await cli.sanity(selection, experiment.cache, sanity_output)
    assert gate["passed"] and gate["complete"]
    assert len(calls) == 2
    probe = experiment.root / "offline-probe.json"
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {
                "network.py": file_sha256(Path(study.__file__).with_name("network.py"))
            },
        },
    )
    args = freeze_arguments(experiment, sanity_output / "sanity.json", probe)
    frozen = cli.freeze(args)
    assert "private-never-publish" not in json.dumps(frozen)
    experiment.manifest_path = args.output
    experiment.output = experiment.root / "dev-results"
    result = await run_phase(experiment)
    assert len(calls) == 6
    assert result["groups"]["baseline"]["successes"] == 1
    report = experiment.root / "dev-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "report",
            "--manifest",
            str(args.output),
            "--records",
            str(experiment.output / "records.jsonl"),
            "--output",
            str(report),
        ],
    )
    assert cli.main() == 0
    assert read_json(report) == read_json(experiment.output / "summary.json")
    assert read_json(report)["formal_comparison_eligible"] is False


async def test_replay_failure_preserves_paid_source_record_and_blocks_implicit_resume(
    experiment: Any,
    monkeypatch: Any,
) -> None:
    calls = install_jobs(monkeypatch)

    async def fail_replay(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("verification infrastructure failed")

    monkeypatch.setattr(study, "replay_official_trial", fail_replay)
    with pytest.raises(RuntimeError):
        await run_phase(experiment)
    records = [
        json.loads(line)
        for line in (experiment.output / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1 and records[0]["input_tokens"] == 100
    assert records[0]["record_complete"] is False
    assert (experiment.output / "abort.json").exists()
    assert "experiment_aborted" in read_json(experiment.output / "summary.json")["validity_issues"]
    with pytest.raises(ValueError):
        await run_phase(experiment)
    assert len(calls) == 1


async def test_calibration_resume_rejects_changed_variant(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    await run_phase(experiment)
    write_json(experiment.variants["candidate"], {"id": "changed", "team_enabled": False})
    with pytest.raises(ValueError, match="身份"):
        await run_phase(experiment)
    assert len(calls) == 4


async def test_output_must_not_pollute_official_cache_or_publish_private_profiles(
    experiment: Any,
    monkeypatch: Any,
) -> None:
    calls = install_jobs(monkeypatch)
    experiment.output = experiment.task / "results"
    with pytest.raises(ValueError):
        await run_phase(experiment)
    assert not calls
    experiment.output = experiment.root / "results"
    experiment.private = experiment.output / "private"
    with pytest.raises(ValueError):
        await run_phase(experiment)
    assert not calls


async def test_changed_profile_is_rejected_before_second_paid_trial(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    await run_phase(experiment)
    profile = read_json(experiment.connections["local"])
    profile["context_length"] = 128000
    write_json(experiment.connections["local"], profile)
    with pytest.raises(ValueError):
        await run_phase(experiment)
    assert len(calls) == 4


def test_cli_report_cannot_remove_abort_with_complete_records(
    experiment: Any, monkeypatch: Any
) -> None:
    manifest = {**experiment.manifest, "phase": "holdout", "candidate": "candidate"}
    write_json(experiment.manifest_path, manifest)
    experiment.output.mkdir()
    write_json(experiment.output / "abort.json", {"reason": "operator_interrupt"})
    records = [
        {
            "task_id": experiment.task.name,
            "configuration": name,
            "repeat": 1,
            "canonical_model": CANONICAL_MODEL,
            "endpoint": "local",
            "status": "completed",
            "verified": True,
            "success": True,
            "record_complete": True,
        }
        for name in experiment.variants
    ]
    records_path = experiment.output / "records.jsonl"
    records_path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    report = experiment.root / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "report",
            "--manifest",
            str(experiment.manifest_path),
            "--records",
            str(records_path),
            "--output",
            str(report),
        ],
    )
    assert cli.main() == 0
    result = read_json(report)
    assert result["formal_comparison_eligible"] is False
    assert "experiment_aborted" in result["validity_issues"]


@pytest.mark.parametrize(
    "changed", ["revision", "config_sha256", "task_tree_sha256", "network_sha256"]
)
def test_freeze_rejects_stale_preflight_even_when_task_id_matches(
    experiment: Any,
    changed: str,
) -> None:
    selection = experiment.root / "selection.json"
    write_json(selection, {"dev": experiment.manifest["tasks"], "holdout": []})
    gate = {
        "benchmark": experiment.manifest["benchmark"],
        "revision": experiment.manifest["revision"],
        "complete": True,
        "passed": True,
        "tasks": [{**experiment.manifest["tasks"][0], "passed": True}],
    }
    probe = {
        "passed": True,
        "cleanup_confirmed": True,
        "source_sha256": {"network.py": file_sha256(Path(study.__file__).with_name("network.py"))},
    }
    if changed == "revision":
        gate["revision"] = "0" * 40
    elif changed == "network_sha256":
        probe["source_sha256"]["network.py"] = "0" * 64
    else:
        gate["tasks"][0][changed] = "0" * 64
    gate_path, probe_path = experiment.root / "gate.json", experiment.root / "probe.json"
    write_json(gate_path, gate)
    write_json(probe_path, probe)
    args = argparse.Namespace(
        phase="dev",
        selection=selection,
        sanity=gate_path,
        network_probe=probe_path,
        variant=[f"{name}={path}" for name, path in experiment.variants.items()],
        connection=[f"{name}={path}" for name, path in experiment.connections.items()],
        repeats=1,
        seed="offline",
        reported_token_limit=10000,
        wheel=experiment.wheel,
        requirements=experiment.requirements,
        output=experiment.root / "frozen.json",
        candidate_lock=None,
    )
    with pytest.raises(ValueError):
        cli.freeze(args)
    assert not args.output.exists()


def paid_policy(
    bundle: Any, *, limit_cny: float = 100, prior: list[Path] | None = None
) -> dict[str, Any]:
    source = (
        Path(study.__file__).resolve().parents[2]
        / "studies"
        / "prices"
        / "siliconflow-deepseek-v4.1-flash-20261022.json"
    )
    snapshot = bundle.root / "price.json"
    snapshot.write_bytes(source.read_bytes())
    policy = study.freeze_paid_budget(
        limit_cny=limit_cny, price_snapshot=snapshot, prior_records=prior
    )
    assert policy is not None
    return policy


def use_paid_connection(bundle: Any, policy: dict[str, Any]) -> None:
    profile = bundle.connections["local"]
    bundle.connections = {"remote": profile}
    bundle.manifest["connections"] = ["remote"]
    bundle.manifest["connection_profiles"]["remote"] = bundle.manifest["connection_profiles"].pop(
        "local"
    )
    bundle.manifest["paid_budget"] = policy
    write_json(bundle.manifest_path, bundle.manifest)


def prior_usage(index: int, input_tokens: int) -> dict[str, Any]:
    return {
        "job_dir": f"C:/earlier-stage/jobs/trial-{index}",
        "request_sha256": f"{index:064x}",
        "endpoint": "remote",
        "task_id": f"prior-{index}",
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "usage_complete": True,
        "usage": {
            "model_calls": 1,
            "reported_calls": 1,
            "missing_usage_calls": 0,
            "damaged_audit_lines": 0,
        },
    }


def gate_and_probe(bundle: Any) -> tuple[Path, Path]:
    gate, probe = bundle.root / "gate.json", bundle.root / "probe.json"
    write_json(
        gate,
        {
            "benchmark": bundle.manifest["benchmark"],
            "revision": bundle.manifest["revision"],
            "complete": True,
            "passed": True,
            "tasks": [
                {
                    **bundle.manifest["tasks"][0],
                    "passed": True,
                    "oracle": {
                        "runtime_identity": {
                            "available": True,
                            "image_id": "sha256:" + "a" * 64,
                            "architecture": "amd64",
                            "os": "linux",
                        }
                    },
                }
            ],
        },
    )
    write_json(
        probe,
        {
            "passed": True,
            "cleanup_confirmed": True,
            "source_sha256": {
                "network.py": file_sha256(Path(study.__file__).with_name("network.py")),
            },
        },
    )
    return gate, probe


def test_freeze_paid_budget_binds_prices_prior_records_and_no_raw_connection(
    experiment: Any,
) -> None:
    earlier = []
    for index, name in enumerate(("dev", "holdout"), 1):
        path = experiment.root / f"{name}-records.jsonl"
        path.write_text(json.dumps(prior_usage(index, index * 1_000_000)) + "\n", encoding="utf-8")
        earlier.append(path)
    policy = paid_policy(experiment, limit_cny=10, prior=earlier)
    gate, probe = gate_and_probe(experiment)
    args = freeze_arguments(experiment, gate, probe)
    args.paid_limit_cny = 10
    args.paid_price_snapshot = Path(policy["price_snapshot"]["path"])
    args.prior_records = earlier
    frozen = cli.freeze(args)
    saved = frozen["paid_budget"]
    assert saved["limit_cny"] == 10 and saved["stop_fraction"] == 0.8
    assert saved["input_cny_per_million"] == 2 and saved["output_cny_per_million"] == 8
    assert len(saved["prior_records"]) == 2
    assert all(
        reference["sha256"] == file_sha256(Path(reference["path"]))
        for reference in saved["prior_records"]
    )
    assert saved["price_snapshot"]["sha256"] == file_sha256(args.paid_price_snapshot)
    assert "private-never-publish" not in json.dumps(frozen)
    assert "api_key" not in json.dumps(saved)


async def test_paid_threshold_stops_after_current_pristine_replay_once(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    use_paid_connection(experiment, paid_policy(experiment, limit_cny=0.0003))
    result = await run_phase(experiment)
    assert len(calls) == 2
    assert (
        read_json(experiment.output / "abort.json")["reason"]
        == "paid_estimate_stop_fraction_reached"
    )
    budget = result["paid_budget"]
    assert budget["paid_records"] == 1
    assert budget["known_estimate_cny"] == pytest.approx(0.00028)
    assert budget["provider_enforced_currency_cap"] is False
    assert read_json(experiment.output / "budget.json") == budget
    assert len(result["missing_trials"]) == 1
    report = experiment.root / "fee-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "report",
            "--manifest",
            str(experiment.manifest_path),
            "--records",
            str(experiment.output / "records.jsonl"),
            "--output",
            str(report),
        ],
    )
    assert cli.main() == 0
    assert read_json(report) == read_json(experiment.output / "summary.json")
    assert "private-never-publish" not in json.dumps(read_json(report))


async def test_all_prior_stage_fees_stop_before_first_paid_call(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    prior = []
    for index in (1, 2):
        path = experiment.root / f"prior-stage-{index}.jsonl"
        path.write_text(json.dumps(prior_usage(index, 1_000_000)) + "\n", encoding="utf-8")
        prior.append(path)
    use_paid_connection(experiment, paid_policy(experiment, limit_cny=5, prior=prior))
    result = await run_phase(experiment)
    assert not calls
    assert result["paid_budget"]["known_estimate_cny"] == 4
    assert result["paid_budget"]["paid_records"] == 2
    assert result["paid_budget"]["local_cost_cny"] is None
    assert (
        read_json(experiment.output / "abort.json")["reason"]
        == "paid_estimate_stop_fraction_reached"
    )


async def test_missing_paid_usage_stops_new_paid_calls_but_preserves_source(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    original = execution.normalize_trial_result

    def incomplete(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        if result["usage"]:
            result["usage"].pop("damaged_audit_lines", None)
            result["usage_complete"] = False
        return result

    monkeypatch.setattr(execution, "normalize_trial_result", incomplete)
    use_paid_connection(experiment, paid_policy(experiment))
    result = await run_phase(experiment)
    assert len(calls) == 2
    assert read_json(experiment.output / "abort.json")["reason"] == "paid_usage_incomplete"
    assert result["paid_budget"]["usage_complete"] is False
    assert result["paid_budget"]["missing_usage_calls"] is None
    assert result["paid_budget"]["known_estimate_cny"] == pytest.approx(0.00028)


async def test_local_usage_is_unpriced_not_free_or_paid_incomplete(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    experiment.manifest["paid_budget"] = paid_policy(experiment, limit_cny=0.001)
    write_json(experiment.manifest_path, experiment.manifest)
    result = await run_phase(experiment)
    assert len(calls) == 4
    assert result["paid_budget"]["known_estimate_cny"] == 0
    assert result["paid_budget"]["unpriced_endpoints"] == ["local"]
    assert result["paid_budget"]["local_cost_cny"] is None
    assert result["paid_budget"]["total_bill_cny"] is None
    assert not (experiment.output / "abort.json").exists()


@pytest.mark.parametrize("which", ["prior_records", "price_snapshot"])
async def test_changed_frozen_fee_file_is_rejected_before_model_calls(
    experiment: Any, monkeypatch: Any, which: str
) -> None:
    calls = install_jobs(monkeypatch)
    prior = experiment.root / "prior.jsonl"
    prior.write_text(json.dumps(prior_usage(1, 1)) + "\n", encoding="utf-8")
    policy = paid_policy(experiment, prior=[prior])
    use_paid_connection(experiment, policy)
    target = Path(policy["price_snapshot"]["path"]) if which == "price_snapshot" else prior
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="发生变化"):
        await run_phase(experiment)
    assert not calls


async def test_prior_fee_file_changed_during_trial_stops_before_next_trial(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    prior = experiment.root / "prior.jsonl"
    prior.write_text(json.dumps(prior_usage(1, 1)) + "\n", encoding="utf-8")
    use_paid_connection(experiment, paid_policy(experiment, prior=[prior]))
    original = study.replay_official_trial

    async def replay_then_change(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await original(*args, **kwargs)
        prior.write_text(prior.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return result

    monkeypatch.setattr(study, "replay_official_trial", replay_then_change)
    result = await run_phase(experiment)
    assert len(calls) == 2
    assert read_json(experiment.output / "abort.json")["reason"] == "paid_budget_evidence_changed"
    assert result["paid_budget"]["evidence_valid"] is False
    assert result["formal_comparison_eligible"] is False


def test_cli_prepare_passes_explicit_calibration_group_exclusions(
    experiment: Any, monkeypatch: Any
) -> None:
    seen = {}

    def select(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(dev=[], holdout=[], eligible_count=2)

    monkeypatch.setattr(cli, "build_catalog", lambda *args: [])
    monkeypatch.setattr(cli, "select_tasks", select)
    monkeypatch.setattr(cli, "write_manifest", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sayacode-bench",
            "prepare",
            "--benchmark",
            "swe-bench-pro-v2",
            "--cache",
            str(experiment.cache),
            "--dev",
            "1",
            "--holdout",
            "1",
            "--seed",
            "fixed",
            "--exclude-leakage-group",
            "repo/one:fix",
            "--exclude-leakage-group",
            "repo/two:fix",
            "--output",
            str(experiment.root / "selection.json"),
        ],
    )
    assert cli.main() == 0
    assert seen["excluded_leakage_groups"] == ("repo/one:fix", "repo/two:fix")


def test_no_implicit_paid_budget_or_runtime_amount_override() -> None:
    assert study.freeze_paid_budget(limit_cny=None) is None
    with pytest.raises(ValueError, match="显式"):
        study.freeze_paid_budget(limit_cny=None, prior_records=[Path("prior.jsonl")])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "run",
                "--manifest",
                "study.json",
                "--cache",
                "cache",
                "--output",
                "results",
                "--variant",
                "baseline=baseline.json",
                "--connection",
                "remote=private.json",
                "--wheel",
                "product.whl",
                "--requirements",
                "requirements.txt",
                "--paid-limit-cny",
                "999",
            ]
        )


def test_price_policy_cannot_silently_use_off_peak_instead_of_frozen_peak(experiment: Any) -> None:
    policy = paid_policy(experiment)
    path = Path(policy["price_snapshot"]["path"])
    snapshot = read_json(path)
    snapshot["conservative_estimation"]["input_cny_per_million"] = 1
    write_json(path, snapshot)
    with pytest.raises(ValueError, match="最高"):
        study.freeze_paid_budget(limit_cny=100, price_snapshot=path)


def test_invalid_fee_evidence_cancels_final_validation_eligibility(experiment: Any) -> None:
    policy = paid_policy(experiment)
    manifest = {
        **experiment.manifest,
        "phase": "validation",
        "configurations": ["baseline"],
        "candidate": None,
        "paid_budget": policy,
    }
    row = {
        **prior_usage(1, 100),
        "task_id": experiment.task.name,
        "configuration": "baseline",
        "repeat": 1,
        "canonical_model": CANONICAL_MODEL,
        "status": "completed",
        "verified": True,
        "success": True,
    }
    valid = study.phase_summary(manifest, [row])
    assert valid["formal_validation_eligible"] is True
    assert valid["final_result_eligible"] is True
    price = Path(policy["price_snapshot"]["path"])
    price.write_text(price.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    invalid = study.phase_summary(manifest, [row])
    assert invalid["paid_budget"]["evidence_valid"] is False
    assert invalid["formal_comparison_eligible"] is False
    assert invalid["formal_validation_eligible"] is False
    assert invalid["final_result_eligible"] is False
    assert "paid_budget_evidence_invalid" in invalid["validity_issues"]


async def test_missing_runtime_stops_next_trial_without_erasing_official_grade(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    native_normalize = execution.normalize_trial_result

    def missing_identity(*args: Any, **kwargs: Any) -> dict[str, Any]:
        row = native_normalize(*args, **kwargs)
        row.pop("runtime_identity", None)
        return row

    monkeypatch.setattr(execution, "normalize_trial_result", missing_identity)
    experiment.manifest["runtime_evidence_required"] = True
    write_json(experiment.manifest_path, experiment.manifest)
    report = await run_phase(experiment)
    assert len(calls) == 2  # 一次实际执行和一次独立重判，下一配置没有启动。
    abort = read_json(experiment.output / "abort.json")
    assert abort["reason"] == "runtime_evidence_unconfirmed"
    rows = [
        json.loads(line)
        for line in (experiment.output / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["replay_reward"] == 1
    assert "experiment_aborted" in report["validity_issues"]


@pytest.mark.parametrize("comparison", [None, {}, {"same_image": False, "same_platform": True}])
def test_unconfirmed_replay_runtime_is_not_accepted(comparison: Any) -> None:
    assert not study._runtime_confirmed(
        {
            "runtime_identity": {
                "available": True,
                "image_id": "sha256:1",
                "architecture": "amd64",
                "os": "linux",
            },
            "runtime_comparison": comparison,
        },
        replay=True,
    )


@pytest.mark.parametrize("mode", ["public", "no-network"])
async def test_model_address_matches_actual_official_agent_network(
    experiment: Any, monkeypatch: Any, mode: str
) -> None:
    calls = install_jobs(monkeypatch)
    experiment.manifest["tasks"][0]["agent"] = {"network_mode": mode}
    write_json(experiment.manifest_path, experiment.manifest)
    await run_phase(experiment)
    path = Path(calls[0].agents[0].kwargs["profile_path"])
    expected = "https://model.invalid/v1" if mode == "public" else "http://saya-model-gateway:8080"
    assert read_json(path)["base_url"] == expected


def test_runtime_image_must_match_qualification_not_only_replay() -> None:
    source = {"available": True, "image_id": "sha256:new", "architecture": "amd64", "os": "linux"}
    assert not study._runtime_confirmed(
        {
            "runtime_identity": source,
            "runtime_comparison": {"same_image": True, "same_platform": True},
        },
        replay=True,
        qualified={**source, "image_id": "sha256:old"},
    )


async def test_formal_manifest_cannot_omit_qualified_images(
    experiment: Any, monkeypatch: Any
) -> None:
    calls = install_jobs(monkeypatch)
    experiment.manifest.update(
        phase="dev",
        preflight_passed=True,
        implementation=study.implementation_identity(),
        artifacts={
            "product_wheel": file_sha256(experiment.wheel),
            "requirements": file_sha256(experiment.requirements),
            "variants": {name: file_sha256(path) for name, path in experiment.variants.items()},
        },
    )
    write_json(experiment.manifest_path, experiment.manifest)
    with pytest.raises(ValueError, match="资格镜像"):
        await run_phase(experiment)
    assert calls == []
