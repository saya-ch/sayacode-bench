"""发布前保留原始缓存金融复核，输出仍不包含私有旁证路径或逐调用内容。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_locking import experiment as experiment
from test_locking import save_records
from test_observed_cache_budget import priced_development

from sayacode_bench import study
from sayacode_bench.artifacts import read_json
from sayacode_bench.publish import export_results


def publish(experiment: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    return export_results(
        experiment["manifest_path"], experiment["records_path"], tmp_path / "public"
    )


def test_valid_observed_cache_cost_survives_publication(
    experiment: dict[str, Any], tmp_path: Path
) -> None:
    priced_development(experiment, tmp_path, invalid=False)
    raw = study.phase_summary(experiment["manifest"], experiment["records"])
    public = publish(experiment, tmp_path)
    assert raw["paid_budget"]["known_estimate_cny"] == pytest.approx(101.02)
    assert public["paid_budget"]["known_estimate_cny"] == raw["paid_budget"]["known_estimate_cny"]
    assert public["paid_budget"]["reported_paid_cache_read_tokens"] == 500_000
    assert public["paid_budget"]["cache_discount_applied"] is True
    assert public["validity_issues"] == raw["validity_issues"] == []
    assert public["groups"] == raw["groups"]
    assert public["paid_budget"]["stop_reason"] == "paid_estimate_stop_fraction_reached"


@pytest.mark.parametrize("kind", ["invalid_summary", "changed_sidecar"])
def test_invalid_native_cache_does_not_become_valid_during_publication(
    experiment: dict[str, Any], tmp_path: Path, kind: str
) -> None:
    priced_development(experiment, tmp_path, invalid=kind == "invalid_summary")
    if kind == "changed_sidecar":
        Path(experiment["records"][-1]["usage_details"]["path"]).write_text(
            "changed native evidence", encoding="utf-8"
        )
    raw = study.phase_summary(experiment["manifest"], experiment["records"])
    public = publish(experiment, tmp_path)
    assert public["paid_budget"]["usage_complete"] is False
    assert public["paid_budget"]["stop_reason"] == "paid_usage_incomplete"
    assert "paid_usage_incomplete" in public["validity_issues"]
    assert public["formal_comparison_eligible"] is False
    assert public["formal_validation_eligible"] is False
    assert public["final_result_eligible"] is False
    assert public["groups"] == raw["groups"]
    assert (
        "paid_usage_incomplete" in read_json(tmp_path / "public/manifest.json")["validity_issues"]
    )


def test_financial_recheck_does_not_publish_paths_calls_or_private_body(
    experiment: dict[str, Any], tmp_path: Path
) -> None:
    priced_development(experiment, tmp_path, invalid=False)
    row = experiment["records"][-1]
    row["cache_usage"].update(
        calls=[{"run_id": "private-call-id", "api_key": "private-provider-key"}],
        path=str(tmp_path / "private-directory"),
        response={"text": "private response body"},
    )
    save_records(experiment)
    public = publish(experiment, tmp_path)
    text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "public").iterdir())
    for private in (
        str(tmp_path),
        row["usage_details"]["path"],
        "private-call-id",
        "private-provider-key",
        "private response body",
        "private-directory",
    ):
        assert private not in text
    assert public["paid_budget"]["price_snapshot"] == {
        "sha256": experiment["manifest"]["paid_budget"]["price_snapshot"]["sha256"]
    }
    records = [
        json.loads(line)
        for line in (tmp_path / "public/records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["evidence"]["usage_details"] == {"sha256": row["usage_details"]["sha256"]}
    assert "usage_details" not in records[-1] and "calls" not in records[-1]["cache_usage"]
