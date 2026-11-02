"""断点自愈脚本的单元测试；只操作临时目录，不依赖真实 Docker 或模型。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import auto_resume


def make_job(root: Path, agent: str, kind: str, name: str, payload: dict | None) -> Path:
    job = root / agent / Path(kind) / name
    job.mkdir(parents=True)
    if payload is not None:
        (job / "normalized.json").write_text(json.dumps(payload), encoding="utf-8")
    return job


def build_root(tmp_path: Path) -> Path:
    root = tmp_path / "results"
    make_job(root, "sayacode", "jobs", "job-done", {"record_complete": True, "status": "completed"})
    make_job(
        root,
        "sayacode",
        "jobs",
        "job-incomplete",
        {"record_complete": False, "status": "running", "failure_category": "timeout"},
    )
    make_job(root, "sayacode", "jobs", "job-no-record", None)
    make_job(root, "mini-swe", "verify/jobs", "verify-job", {"record_complete": False})
    (root / "sayacode" / "jobs" / "job-broken").mkdir(parents=True)
    (root / "sayacode" / "jobs" / "job-broken" / "normalized.json").write_text(
        "{oops", encoding="utf-8"
    )
    return root


def test_classify_job_three_way(tmp_path: Path) -> None:
    root = tmp_path / "r"
    done = make_job(root, "a", "jobs", "done", {"record_complete": True})
    inc = make_job(root, "a", "jobs", "inc", {"record_complete": False, "status": "errored"})
    no_record = make_job(root, "a", "jobs", "none", None)
    broken = make_job(root, "a", "jobs", "bad", None)
    (broken / "normalized.json").write_text("{", encoding="utf-8")
    missing_field = make_job(root, "a", "jobs", "missing", {"status": "completed"})

    assert auto_resume.classify_job(done).classification == auto_resume.COMPLETED
    assert auto_resume.classify_job(inc).classification == auto_resume.INCOMPLETE
    assert auto_resume.classify_job(inc).status == "errored"
    assert auto_resume.classify_job(no_record).classification == auto_resume.NO_RESULT
    assert auto_resume.classify_job(broken).classification == auto_resume.NO_RESULT
    assert auto_resume.classify_job(missing_field).classification == auto_resume.NO_RESULT


def test_scan_root_keeps_agent_and_kind(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    states = auto_resume.scan_root(root)
    by_name = {state.job_dir.name: state for state in states}
    assert by_name["job-done"].classification == auto_resume.COMPLETED
    assert by_name["job-done"].agent == "sayacode"
    assert by_name["job-done"].kind == "jobs"
    assert by_name["verify-job"].agent == "mini-swe"
    assert by_name["verify-job"].kind == "verify/jobs"
    residual = {state.job_dir.name for state in states if state.residual}
    assert residual == {"job-incomplete", "job-no-record", "job-broken", "verify-job"}


def test_plan_moves_only_residual_and_nested_structure(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    states = auto_resume.scan_root(root)
    plans = auto_resume.plan_moves(states, root, "20261102T000000Z")
    target_names = {plan.source.name for plan in plans}
    assert "job-done" not in target_names
    assert target_names == {"job-incomplete", "job-no-record", "job-broken", "verify-job"}
    verify_plan = next(plan for plan in plans if plan.source.name == "verify-job")
    assert verify_plan.target == (
        root / "abandoned-auto-20261102T000000Z" / "mini-swe" / "verify" / "jobs" / "verify-job"
    )


def test_apply_moves_jobs(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    states = auto_resume.scan_root(root)
    plans = auto_resume.plan_moves(states, root, "stamp")
    auto_resume.apply_moves(plans)
    for plan in plans:
        assert not plan.source.exists()
        assert plan.target.is_dir()
    # 已完成的不动
    assert (root / "sayacode" / "jobs" / "job-done").is_dir()


def test_main_dry_run_does_not_move(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    code = auto_resume.main(
        ["--root", str(root), "--no-docker", "--json-out", str(tmp_path / "o.json")]
    )
    assert code == 0
    assert (root / "sayacode" / "jobs" / "job-incomplete").is_dir()
    payload = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "dry-run"
    assert payload["moves"] == []
    assert len(payload["planned_moves"]) == 4
    assert payload["scan"]["counts"] == {"completed": 1, "incomplete": 2, "no_result": 2}
    assert any("run_formal_240.py" in command for command in payload["resume_commands"])


def test_main_apply_moves_and_reports(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    code = auto_resume.main(["--root", str(root), "--apply", "--no-docker"])
    assert code == 0
    assert not (root / "sayacode" / "jobs" / "job-incomplete").exists()
    assert list(root.glob("abandoned-auto-*"))


def test_apply_and_dry_run_conflict(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    try:
        auto_resume.main(["--root", str(root), "--apply", "--dry-run", "--no-docker"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("互斥参数应报错")


def test_probe_docker_offline() -> None:
    def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=1, stdout="", stderr="Cannot connect to the Docker daemon"
        )

    status = auto_resume.probe_docker(runner)
    assert status.online is False
    assert "Cannot connect" in (status.error or "")


def test_probe_docker_online_filters_system_containers() -> None:
    def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
        if argv[0] == "info":
            return SimpleNamespace(returncode=0, stdout="29.7.2\n", stderr="")
        if argv[0] == "ps":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "dsh-web|Up 8 hours|dsh-web:0.2.0\n"
                    "harbor-instance-abc|Exited (1)|swe-bench-pro-v2:latest\n"
                ),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout="bridge\ndsh-web_default\nsaya-isolated-abc123\n",
            stderr="",
        )

    status = auto_resume.probe_docker(runner)
    assert status.online is True
    assert status.server_version == "29.7.2"
    assert [item["name"] for item in status.eval_containers] == ["harbor-instance-abc"]
    assert status.eval_networks == ("saya-isolated-abc123",)


def test_prune_docker_only_touches_eval_residuals() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    status = auto_resume.DockerStatus(
        online=True,
        eval_containers=({"name": "harbor-1", "status": "Exited", "image": "swe-bench"},),
        eval_networks=("saya-isolated-x",),
    )
    actions = auto_resume.prune_docker(status, runner)
    assert actions == ["rm container harbor-1", "rm network saya-isolated-x"]
    assert ["rm", "-f", "harbor-1"] in calls
    assert ["network", "rm", "saya-isolated-x"] in calls


def test_resume_commands_include_agents(tmp_path: Path) -> None:
    commands = auto_resume.resume_commands(tmp_path, ["sayacode", "mini-swe"])
    assert "--agents mini-swe sayacode" in commands[0]
    assert "verify_patches.py" in commands[1]
