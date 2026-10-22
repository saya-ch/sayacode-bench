"""公开工件只能保留白名单事实，且不能抹去中止状态。"""

import json

import pytest

from sayacode_bench import publish
from sayacode_bench.analysis import analyze_experiment
from sayacode_bench.publish import export_results, public_record, validate_public


def record():
    return {
        "task_id": "task-a",
        "configuration": "baseline",
        "repeat": 1,
        "canonical_model": "DeepSeek-V4.1-Flash",
        "endpoint": "local",
        "status": "completed",
        "success": True,
        "verified": True,
        "record_complete": True,
        "worker_result": {"path": "C:\\private\\result.json", "sha256": "a" * 64},
        "job_dir": "C:\\private",
        "api_key": "never-export-this",
        "messages": [{"content": "private reasoning"}],
        "usage": {"model_calls": 1, "raw_response": "private provider body"},
    }


def test_public_facts_do_not_copy_unknown_or_nested_private_fields():
    result = public_record(record())
    text = json.dumps(result)
    assert "private" not in text
    assert "api_key" not in text
    assert result["evidence"]["worker_result"] == {"sha256": "a" * 64}
    assert result["usage"] == {"model_calls": 1}


@pytest.mark.parametrize(
    "field,value", [("endpoint", "sk-" + "x" * 30), ("failure_category", "C:\\Users\\user")]
)
def test_suspicious_public_value_is_rejected(field, value):
    row = record()
    row[field] = value
    with pytest.raises(ValueError):
        public_record(row)


def test_export_keeps_abort_and_is_not_overwritable(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "phase": "validation",
                "frozen": True,
                "canonical_model": "DeepSeek-V4.1-Flash",
                "configurations": ["baseline"],
                "baseline": "baseline",
                "candidate": None,
                "repeats": 1,
                "tasks": [{"task_id": "task-a", "repository": "repo"}],
                "connection_profiles": {"local": {"api_key": "private", "context_length": 65536}},
            }
        ),
        encoding="utf-8",
    )
    records = source / "records.jsonl"
    records.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    (source / "abort.json").write_text(json.dumps({"reason": "quota"}), encoding="utf-8")
    target = tmp_path / "public"
    report = export_results(manifest, records, target)
    assert not report["final_result_eligible"]
    assert report["validity_issues"]
    public_manifest = json.loads((target / "manifest.json").read_text())
    assert public_manifest["connection_profiles"] == {"local": {"context_length": 65536}}
    with pytest.raises(ValueError):
        export_results(manifest, records, target)


def test_nested_runtime_fields_cannot_carry_non_prefixed_keys_or_private_bodies():
    row = record()
    row["runtime_identity"] = {
        "available": True,
        "api_key": "opaque-credential-without-known-prefix",
        "private_body": {"message": "do not publish private reasoning"},
        "image_id": "sha256:" + "b" * 64,
        "repo_digests": ["public/task@sha256:" + "b" * 64],
        "requested": {
            "cpus": 1,
            "memory_mb": 4096,
            "storage_mb": 10240,
            "docker_image": "public/task:fixed",
            "api_key": "opaque-nested-key",
        },
        "docker_limits": {
            "Memory": 4294967296,
            "MemorySwap": 8589934592,
            "StorageOpt": {"size": "10G", "secret": "storage-password"},
            "Env": ["PRIVATE=unpublished"],
        },
    }
    row["runtime_comparison"] = {
        "same_image": True,
        "same_platform": None,
        "raw_response": {"secret": "opaque"},
    }
    result = public_record(row)
    text = json.dumps(result)
    assert "opaque" not in text and "reasoning" not in text and "password" not in text
    assert result["runtime_identity"]["requested"] == {
        "cpus": 1,
        "memory_mb": 4096,
        "storage_mb": 10240,
        "docker_image": "public/task:fixed",
    }
    assert result["runtime_identity"]["docker_limits"]["StorageOpt"] == {"size": "10G"}
    assert result["runtime_comparison"] == {"same_image": True, "same_platform": None}


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": {"secret": "opaque"}},
        {"input_tokens": True},
        {"duration_seconds": float("inf")},
        {"child_roles": [{"private": "body"}]},
        {"runtime_identity": {"available": "true"}},
        {"runtime_identity": {"available": True, "requested": {"cpus": "one"}}},
        {"runtime_identity": {"available": True, "repo_digests": [None]}},
        {"runtime_comparison": {"same_image": 1}},
    ],
)
def test_known_public_fields_require_their_declared_types(mutation):
    with pytest.raises(ValueError):
        public_record({**record(), **mutation})


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "api-key",
        "apiKey",
        "Authorization",
        "secret",
        "password",
        "client_secret",
        "access_token",
        "private_key",
    ],
)
def test_recursive_guard_rejects_opaque_credentials_by_key(key):
    with pytest.raises(ValueError):
        validate_public({"report": {"nested": [{key: "opaque-without-sk-prefix"}]}})


@pytest.mark.parametrize(
    "value",
    [
        r"C:\Users\private-user\project",
        "C:/private/project",
        r"\\server\private\file",
        "/home/private-user/project",
        "/Users/private-user/file",
        "/root/private/file",
        "/custom-user-volume/project",
        "notes in /tmp/private-output/file",
        "https://example.test?api_key=opaque",
        "https://user:opaque@example.test/path",
        "sk-" + "A" * 30,
    ],
)
def test_recursive_guard_rejects_user_paths_and_credentials(value):
    with pytest.raises(ValueError):
        validate_public({"scope": value})


@pytest.mark.parametrize(
    "value",
    [
        "https://github.com/org/repo/tree/main/home/example",
        "https://example.test/Users/public/document",
        "http://localhost:1234/api/docs",
        "public/task@sha256:" + "a" * 64,
    ],
)
def test_public_http_links_are_not_mistaken_for_local_paths(value):
    validate_public({"scope": value})


def test_network_evidence_keeps_only_hashes():
    row = record()
    row["network_isolation"] = {"path": "/home/private/network.json", "sha256": "c" * 64}
    row["replay_network_isolation"] = {"path": r"C:\private\network.json", "sha256": "d" * 64}
    result = public_record(row)
    assert result["evidence"]["network_isolation"] == {"sha256": "c" * 64}
    assert result["evidence"]["replay_network_isolation"] == {"sha256": "d" * 64}


def source_files(tmp_path, *, extra_manifest=None):
    raw = tmp_path / "raw"
    raw.mkdir()
    manifest = raw / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "phase": "validation",
                "frozen": True,
                "canonical_model": "DeepSeek-V4.1-Flash",
                "configurations": ["baseline"],
                "baseline": "baseline",
                "candidate": None,
                "repeats": 1,
                "tasks": [{"task_id": "task-a", "repository": "repo"}],
                **(extra_manifest or {}),
            }
        ),
        encoding="utf-8",
    )
    records = raw / "records.jsonl"
    records.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    return manifest, records


@pytest.mark.parametrize(
    "scope", [r"C:\Users\private\run", "/home/private/run", {"secret": "opaque"}]
)
def test_manifest_scope_cannot_publish_paths_or_nested_private_bodies(tmp_path, scope):
    manifest, records = source_files(tmp_path, extra_manifest={"scope": scope})
    output = tmp_path / "public"
    with pytest.raises(ValueError):
        export_results(manifest, records, output)
    assert not output.exists()


def test_profile_explicit_parameters_preserved_and_unknown_provider_body_dropped(tmp_path):
    manifest, records = source_files(
        tmp_path,
        extra_manifest={
            "provider_parameters": {"api_key": "opaque-top-level"},
            "connection_profiles": {
                "local": {
                    "api_key": "opaque-private",
                    "base_url": "https://private.invalid",
                    "context_length": 65536,
                    "max_output_tokens": 8192,
                    "summary_trigger_tokens": 32000,
                    "summary_trigger_ratio": None,
                    "context_edit_trigger": None,
                    "native_tool_search_tools": ["file_search"],
                    "provider_parameters": {"private_response": "secret body"},
                }
            },
        },
    )
    output = tmp_path / "public"
    export_results(manifest, records, output)
    result = json.loads((output / "manifest.json").read_text())
    assert "provider_parameters" not in result
    profile = result["connection_profiles"]["local"]
    assert profile["summary_trigger_tokens"] == 32000
    assert profile["context_edit_trigger"] is None
    assert profile["native_tool_search_tools"] == ["file_search"]
    assert "opaque" not in json.dumps(result) and "secret body" not in json.dumps(result)


def test_derived_budget_invalidity_remains_invalid_when_public_data_is_reanalyzed(tmp_path):
    manifest, records = source_files(
        tmp_path, extra_manifest={"paid_budget": {"prior_records": []}}
    )
    output = tmp_path / "public"
    result = export_results(manifest, records, output)
    published = json.loads((output / "manifest.json").read_text())
    rows = [json.loads(line) for line in (output / "records.jsonl").read_text().splitlines()]
    assert result["final_result_eligible"] is False
    assert "paid_budget_evidence_invalid" in published["validity_issues"]
    assert analyze_experiment(published, rows)["final_result_eligible"] is False


def test_report_is_recursively_validated_before_creating_public_directory(tmp_path, monkeypatch):
    manifest, records = source_files(tmp_path)
    original = publish.phase_summary

    def contaminated(*args, **kwargs):
        return {**original(*args, **kwargs), "paid_budget": {"nested": {"api_key": "opaque"}}}

    monkeypatch.setattr(publish, "phase_summary", contaminated)
    output = tmp_path / "public"
    with pytest.raises(ValueError):
        export_results(manifest, records, output)
    assert not output.exists()
