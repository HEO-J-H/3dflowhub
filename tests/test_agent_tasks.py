import agents
import manager


def _setup(tmp_path, monkeypatch, props):
    todo = tmp_path / "TODO.md"
    todo.write_text("# TODO\n- [ ] (agent) 기존 과제\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TODO", todo)
    monkeypatch.setattr(manager, "manual_todo", lambda site=None: props)
    return todo


def test_accepted_proposal_queued_once_and_first(tmp_path, monkeypatch):
    p = {"id": "p-0123456789", "title": "가이드 목차 추가", "proposal": "가이드 페이지에\n목차", "category": "사이트·UX"}
    todo = _setup(tmp_path, monkeypatch, [p])
    assert len(agents.queue_manager_tasks()) == 1
    assert agents.queue_manager_tasks() == []  # 중복 등록 없음
    task = agents.next_task()
    assert task.startswith("[p-0123456789|사이트·UX]") and "\n" not in todo.read_text(encoding="utf-8").splitlines()[-1]
    assert agents.files_for(task) == {"build_site.py", "tests/test_agent_tasks.py"}


def test_plain_task_keeps_default_files():
    assert agents.files_for("collect(): 무언가") == agents.EDITABLE


def test_report_marks_done(monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "decide", lambda pid, v, note="": calls.append((pid, v)))
    agents.report_to_manager("[p-0123456789|수집] x", True, "PR #9 머지 완료")
    assert calls == [("p-0123456789", "done")]


def test_target_risk_split_and_files(monkeypatch):
    cfg = agents.TARGETS["pix2poly"]
    monkeypatch.setattr(agents, "TARGET", cfg)
    monkeypatch.setattr(agents, "AUTO_MERGE", cfg["auto_merge"])
    monkeypatch.setattr(agents, "EDITABLE", {"backend/app/main.py", "backend/app/services/pbr_generator.py",
                                             "backend/tests/test_core.py", "docs/system-design.md"})
    assert not agents.needs_approval(["backend/tests/test_core.py", "docs/system-design.md"])  # 자동 머지
    assert agents.needs_approval(["backend/app/services/pbr_generator.py", "backend/tests/test_core.py"])  # 승인 필요
    assert agents.files_for("pbr_generator: 맵 크기 검증") == {"backend/app/services/pbr_generator.py",
                                                            "backend/tests/test_core.py"}
    assert agents.files_for("입력 검증 강화") == {"backend/app/main.py", "backend/tests/test_core.py"}


def test_home_repo_never_needs_approval(monkeypatch):
    monkeypatch.setattr(agents, "AUTO_MERGE", None)
    assert not agents.needs_approval(["core.py"])


def test_pr_decision_recorded_and_skipped_without_token(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "decisions_path", lambda site: tmp_path / "pr_decisions.json")
    monkeypatch.delenv("PIX2POLY_TOKEN", raising=False)
    agents.record_decision("pix2poly", 1, "revise", "실제 엔진 호출까지 구현")
    import core
    items = core._load_json(tmp_path / "pr_decisions.json", [])
    assert items[-1]["pr"] == 1 and items[-1]["v"] == "revise" and items[-1]["done"] is None
    assert agents.apply_pr_decisions("pix2poly") == []  # 토큰 없으면 아무것도 안 함 (기록은 남음)
    import pytest
    with pytest.raises(AssertionError):
        agents.record_decision("pix2poly", 1, "merge-now")
