"""收编仓外 agent 构造与路径配置的测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

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
    assert locked_agents.AGENTS == ("sayacode", "mini-swe", "claude-code", "opencode")


def test_build_agents_use_in_repo_import_paths(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    for name in (*locked_agents.AGENTS, "codex"):  # codex 保留供 v2 历史复现
        config = locked_agents.build_agent(name, paths, profile_dir=tmp_path)
        assert config.model_name
    mini = locked_agents.build_agent("mini-swe", paths, profile_dir=tmp_path)
    assert mini.import_path == "locked_agents:LockedMiniSwe"
    codex = locked_agents.build_agent("codex", paths, profile_dir=tmp_path)
    assert codex.import_path == "locked_agents:LockedCodex"
    claude = locked_agents.build_agent("claude-code", paths, profile_dir=tmp_path)
    assert claude.import_path == "locked_agents:LockedClaudeCode"
    assert claude.env["ANTHROPIC_BASE_URL"] == locked_agents.IN_SANDBOX_GATEWAY
    opencode = locked_agents.build_agent("opencode", paths, profile_dir=tmp_path)
    assert opencode.import_path == "locked_agents:LockedOpenCode"
    assert opencode.model_name == "openai/auto-hy3"
    assert opencode.env["OPENAI_BASE_URL"] == locked_agents.IN_SANDBOX_GATEWAY + "/v1"


def test_sayacode_profile_is_rewritten_to_in_sandbox_gateway(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    config = locked_agents.build_agent("sayacode", paths, profile_dir=tmp_path)
    private = Path(config.kwargs["profile_path"])
    assert (
        json.loads(private.read_text(encoding="utf-8"))["base_url"]
        == locked_agents.IN_SANDBOX_GATEWAY
    )


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


def test_env_cfg_rejects_gateway_without_v1(tmp_path: Path) -> None:
    """网关缺 ``/v1`` 前缀必须在**启动时**失败，而不是让每个 trial 跑 10 秒再死。

    历史事故 2026-11-11：``SAYACODE_BENCH_GATEWAY=http://host.docker.internal:3425``
    （少了 ``/v1``）。``require_inputs`` 只查文件存在与否，查不出来；隔离层要求上游
    路径恰好以 ``/v1/messages`` 结尾，于是 32 个 trial 全部以
    ``ExceptionGroup`` -> ``ValueError`` 秒失败，异常正文不含实际配置值，白跑一批。

    这个测试锁住两点：① 合法网关能构造出正确上游；② 非法网关在 ``env_cfg``
    就抛错，且报错里带**实际构造的地址**与**期望后缀**。
    """
    import dataclasses

    import pytest

    paths = make_paths(tmp_path)

    good = dataclasses.replace(paths, gateway="http://gw:1/v1")
    cfg = locked_agents.env_cfg(good)
    assert cfg.kwargs == {
        "messages_upstream": "http://gw:1/v1/messages",
        "chat_upstream": "http://gw:1/v1/chat/completions",
        "responses_upstream": "http://gw:1/v1/responses",
    }

    # 末尾多写一个 / 应被 rstrip 抹平，不能拼出 //messages
    trailing = dataclasses.replace(paths, gateway="http://gw:1/v1/")
    assert locked_agents.env_cfg(trailing).kwargs["messages_upstream"] == (
        "http://gw:1/v1/messages"
    )

    for bad_gateway in (
        "http://gw:1",  # 缺 /v1 —— 历史事故
        "http://gw:1/v2",  # 版号写错
        "http://user:pw@gw:1/v1",  # 带凭据
        "http://gw:1/v1?x=1",  # 带查询参数
    ):
        bad = dataclasses.replace(paths, gateway=bad_gateway)
        with pytest.raises(ValueError) as excinfo:
            locked_agents.env_cfg(bad)
        message = str(excinfo.value)
        assert "上游地址非法" in message, message
        # 校验按 chat -> messages -> responses 顺序，第一条失败即抛出，
        # 所以这里只断言报错里点名了某个期望的 /v1 后缀与具体地址。
        assert "/v1/" in message, message
        assert bad_gateway.split("//", 1)[1][:6] in message, message


def test_skip_existing_ignores_patch_only(tmp_path: Path) -> None:
    """续跑判据必须是 reward 或 terminal；只有 patch 时不得跳过。

    判据必须按内容识别（``trialdir``），且 **patch 不是完成信号**：
    patch 只用于「无任何产物才归档」的辅助判断。
    （原实现是读源码文本断言；抽成 ``should_skip_existing`` 后改为行为断言。）
    """
    from scripts import run_formal_240

    job_dir = tmp_path / "jobs" / "job-1"
    trial = job_dir / "sweevo-demo__R1"
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "model.patch").write_text("--- a\n+++ b\n", encoding="utf-8")

    assert run_formal_240.should_skip_existing(job_dir, skip_existing=True) is False

    (trial / "verifier").mkdir()
    (trial / "verifier" / "reward.txt").write_text("1.0", encoding="utf-8")
    assert run_formal_240.should_skip_existing(job_dir, skip_existing=True) is True


def test_noop_agent_identity() -> None:
    assert locked_agents.NoOpAgent.name() == "no-op-agent"


# ---------------------------------------------------------------------------
# 缺陷 1 回归：内部 ``timeout`` 的 exit 124 必须映射成 Harbor 的 AgentTimeoutError
# 证据：C:\sb\tmp\audit\infra\ROOTCAUSE.md #01/#07/#12 —— 3 条 trial 跑满
# ``timeout -k 30 2940`` 被杀，Harbor 归成 NonZeroAgentExitCodeError →
# infrastructure_error（可补跑），把「模型用完时间预算」从分母里删掉了。


class _FakeExecResult:
    """只带 ``exec_as_agent`` 关心的字段。"""

    def __init__(self, return_code: int | None) -> None:
        self.return_code = return_code
        self.stdout = ""
        self.stderr = ""


def test_internal_timeout_exit_124_raises_agent_timeout() -> None:
    """124 = 容器内 timeout 触发，必须抛 Harbor 的 AgentTimeoutError。"""
    from harbor.trial.errors import AgentTimeoutError

    with pytest.raises(AgentTimeoutError):
        locked_agents.raise_if_internal_timeout(_FakeExecResult(124), True)


@pytest.mark.parametrize("return_code", [0, 1, 2, 3, 137, None])
def test_internal_timeout_only_remaps_124(return_code: int | None) -> None:
    """其余退出码保持原样：137 是被 KILL，None 是无退出码，都不该冒充超时。"""
    locked_agents.raise_if_internal_timeout(_FakeExecResult(return_code), True)


def test_commands_without_timeout_wrapper_are_not_remapped() -> None:
    """安装、抓补丁等命令不套 timeout，那里的 124 没有「用完时间预算」语义。"""
    locked_agents.raise_if_internal_timeout(_FakeExecResult(124), False)


def test_agent_timeout_error_is_the_class_name_execution_matches() -> None:
    """``execution.py:217`` 按类名匹配 ``AgentTimeoutError``；换名字会退回 infrastructure_error。"""
    from harbor.trial.errors import AgentTimeoutError

    assert AgentTimeoutError.__name__ == "AgentTimeoutError"
    assert issubclass(AgentTimeoutError, asyncio.TimeoutError)


@pytest.mark.parametrize(
    ("agent_class", "command"),
    [
        (locked_agents.LockedMiniSwe, "mini-swe-agent --yolo --model auto-hy3"),
        (locked_agents.LockedCodex, "codex exec --model auto-hy3"),
        (locked_agents.LockedClaudeCode, "claude --print"),
        (locked_agents.LockedOpenCode, "opencode run task"),
    ],
    ids=["mini-swe", "codex", "claude-code", "opencode"],
)
async def test_each_locked_agent_maps_internal_timeout(
    agent_class: type, command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """四个 agent 的 ``exec_as_agent`` 都要接上映射，不能只修一处。"""
    from harbor.trial.errors import AgentTimeoutError

    parents = {
        locked_agents.LockedMiniSwe: locked_agents.MiniSweAgent,
        locked_agents.LockedCodex: locked_agents.Codex,
        locked_agents.LockedClaudeCode: locked_agents.ClaudeCode,
        locked_agents.LockedOpenCode: locked_agents.OpenCode,
    }

    async def fake_exec(self: object, environment: object, command: str, **kwargs: object) -> object:
        return _FakeExecResult(124)

    async def fake_rewrite(environment: object, command: str) -> str:
        return command

    monkeypatch.setattr(parents[agent_class], "exec_as_agent", fake_exec)
    monkeypatch.setattr(locked_agents, "rewrite_if_too_long", fake_rewrite)

    agent = object.__new__(agent_class)
    with pytest.raises(AgentTimeoutError):
        await agent_class.exec_as_agent(agent, None, command)
