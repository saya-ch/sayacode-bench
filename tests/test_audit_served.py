"""audit_served 的合成记录测试（不依赖真实 Magpie 数据）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_served  # noqa: E402


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return path


def rec(agent: str, time: str, served: str | None, provider: str = "workbuddy") -> dict:
    return {"time": time, "agent": agent, "served": served,
            "usage": [{"provider": provider, "model": served or "unknown"}]}


def test_classify_agent_and_dsh_excluded():
    assert audit_served.classify_agent("langchain-anthropic") == "SAYACODE"
    assert audit_served.classify_agent("litellm") == "mini-swe"
    assert audit_served.classify_agent("claude") == "Claude Code"
    assert audit_served.classify_agent("opencode") == "OpenCode"
    assert audit_served.classify_agent("codex") == "Codex"
    assert audit_served.classify_agent("dsh") == "DSH"
    assert audit_served.classify_agent("dsh-mcp-client") == "DSH"
    assert audit_served.classify_agent("something-else") == "unknown"


def test_served_classification():
    assert audit_served.classify_served("hy3") == "hy3"
    assert audit_served.classify_served("hy3-x") == "hy3-x"
    assert audit_served.classify_served("deepseek/deepseek-v4.1-flash") == "deepseek"
    assert audit_served.classify_served("DeepSeek-Flash") == "deepseek"
    assert audit_served.classify_served("glm-5.3-flash") == "glm"
    assert audit_served.classify_served(None) == "unknown"


def test_audit_filters_dsh_and_windows(tmp_path):
    p = write_jsonl(tmp_path / "routing.jsonl", [
        rec("langchain-anthropic", "2026-10-31T10:00:00+08:00", "hy3"),
        rec("litellm", "2026-10-31T11:00:00+08:00", "hy3-x"),
        rec("claude", "2026-10-31T12:00:00+08:00", "hy3"),
        rec("opencode", "2026-10-31T13:00:00+08:00", "deepseek-v4.1-flash"),
        rec("dsh", "2026-10-31T14:00:00+08:00", "deepseek-v4.1-flash"),
        rec("dsh-mcp-client", "2026-10-31T15:00:00+08:00", "glm-5.3-flash"),
        rec("weird-agent", "2026-10-31T16:00:00+08:00", None),
    ])
    result = audit_served.audit(p, "2026-10-31", "2026-10-31")
    assert result["totals"]["records"] == 5, "DSH 两行必须被排除"
    assert result["totals"]["excluded_dsh"] == 2
    assert result["totals"]["by_served"]["hy3"] == 2
    assert result["totals"]["by_served"]["hy3-x"] == 1
    assert result["totals"]["by_served"]["deepseek"] == 1
    assert "unknown" in result["agents"]
    assert result["agents"]["SAYACODE"]["records"] == 1
    assert result["agents"]["mini-swe"]["providers"]["workbuddy"] == 1


def test_window_boundaries_inclusive(tmp_path):
    p = write_jsonl(tmp_path / "routing.jsonl", [
        rec("litellm", "2026-10-31T00:00:00+08:00", "hy3"),
        rec("litellm", "2026-10-31T23:59:59+08:00", "hy3"),
        rec("litellm", "2026-11-01T00:00:00+08:00", "hy3"),
    ])
    result = audit_served.audit(p, "2026-10-31", "2026-10-31")
    assert result["totals"]["records"] == 2, "窗口两端都应包含，窗口外应排除"


def test_comparison_reports_mismatch_without_massaging(tmp_path):
    p = write_jsonl(tmp_path / "routing.jsonl", [
        rec("opencode", "2026-10-29T10:00:00+08:00", "deepseek-v4.1-flash"),
    ])
    result = audit_served.audit(p, None, None)
    cmp = audit_served.compare_with_claims(result, claimed_records=42681, claimed_zero_deepseek=True)
    assert cmp["records_match"] is False
    assert cmp["zero_deepseek_holds_in_observed_window"] is False
    assert any("deepseek" in r for r in cmp["reasons"])
    assert any("42681" in r for r in cmp["reasons"])


def test_gzip_and_metadata(tmp_path):
    import gzip
    recs = [rec("langchain-anthropic", "2026-10-31T10:00:00+08:00", "hy3")]
    with gzip.open(tmp_path / "routing.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    result = audit_served.audit(tmp_path, None, None)
    assert result["totals"]["records"] == 1
    assert result["source"]["files"][0]["records_counted"] == 1
    assert result["source"]["files"][0]["size_bytes"] > 0
