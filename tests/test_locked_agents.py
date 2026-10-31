"""收编仓外 agent 构造与路径配置的测试。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import locked_agents


def make_paths(tmp_path: Path) -> "locked_agents.FormalPaths":
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"model_id": "auto-hy3"}), encoding="utf-8")
    return locked_agents.FormalPaths(
        tasks_root=tmp_path / "tasks",
        profile=profile,
        wheel=tmp_path / "wheel.whl",
        requirements=tmp_path / "requirements.txt",
        variant=tmp_path / "baseline.json",
        sample=tmp_path / "sample.json",
        mini_config=tmp_path / "mini.yaml",
        codex_tarball=tmp_path / "codex.tar.gz",
        out_root=tmp_path,
    )


def test_canonical_model_is_hy3() -> None:
    assert locked_agents.CANONICAL_MODEL == "auto-hy3"
    assert locked_agents.AGENTS == ("sayacode", "mini-swe", "codex")


def test_build_agents_use_in_repo_import_paths(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    for name in ("sayacode", "mini-swe", "codex"):
        config = locked_agents.build_agent(name, paths, profile_dir=tmp_path)
        assert config.model_name
    mini = locked_agents.build_agent("mini-swe", paths, profile_dir=tmp_path)
    assert mini.import_path == "locked_agents:LockedMiniSwe"
    codex = locked_agents.build_agent("codex", paths, profile_dir=tmp_path)
    assert codex.import_path == "locked_agents:LockedCodex"


def test_sayacode_profile_is_rewritten_to_in_sandbox_gateway(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    config = locked_agents.build_agent("sayacode", paths, profile_dir=tmp_path)
    private = Path(config.kwargs["profile_path"])
    assert json.loads(private.read_text(encoding="utf-8"))["base_url"] == locked_agents.IN_SANDBOX_GATEWAY


def test_formal_paths_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAYACODE_BENCH_TASKS_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("SAYACODE_BENCH_GATEWAY", "http://gw:1/v1")
    monkeypatch.setenv("SAYACODE_BENCH_WHEEL", str(tmp_path / "w.whl"))
    paths = locked_agents.FormalPaths.from_env()
    assert paths.tasks_root == tmp_path / "tasks"
    assert paths.gateway == "http://gw:1/v1"
    assert paths.wheel == tmp_path / "w.whl"
    assert paths.tooling == (tmp_path / "tasks").parent / "tooling"


def test_no_out_of_repo_sys_path_insert() -> None:
    root = locked_agents.ROOT
    for script in ("run_formal_240.py", "verify_patches.py", "gold_patch_check.py"):
        source = (root / "scripts" / script).read_text(encoding="utf-8")
        assert 'sys.path.insert(0, r"C:\\sb' not in source, script


def test_run_formal_240_unified_canonical_model() -> None:
    source = (locked_agents.ROOT / "scripts" / "run_formal_240.py").read_text(encoding="utf-8")
    assert "canonical_model=CANONICAL_MODEL" in source
    assert 'canonical_model="DeepSeek-V4.1-Flash" if name == "sayacode"' not in source


def test_skip_existing_ignores_patch_only() -> None:
    source = (locked_agents.ROOT / "scripts" / "run_formal_240.py").read_text(encoding="utf-8")
    assert "verifier/terminal.json" in source
    # 归档/跳过判据都要求 reward 或 terminal；patch 只是附加条件
    assert "not has_patch" in source


def test_noop_agent_identity() -> None:
    assert locked_agents.NoOpAgent.name() == "no-op-agent"
