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


def test_guide_read_new_files_and_lesson_appended(tmp_path, monkeypatch):
    cfg = agents.TARGETS["pix2poly"]
    (tmp_path / "docs" / "agent-guides").mkdir(parents=True)
    g = tmp_path / "docs" / "agent-guides" / "img2threejs.md"
    g.write_text("# 가이드\n\n## 진행 기록·배운 점\n- 처음\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TARGET", cfg)
    monkeypatch.setattr(agents, "ROOT", tmp_path)
    monkeypatch.setattr(agents, "EDITABLE", {"backend/app/main.py", "backend/tests/test_core.py"})
    task = "[guide:img2threejs] 1단계: backend/app/services/engines.py 엔진 목록과 GET /v1/engines"
    rel, text = agents.guide_for(task)
    assert rel == "docs/agent-guides/img2threejs.md" and "가이드" in text
    files = agents.files_for(task)
    assert "backend/app/services/engines.py" in files and "backend/tests/test_core.py" in files  # 새 파일도 열림
    assert "../secret.py" not in agents.files_for(task + " backend/app/../secret.py")
    agents.append_guide_lesson(task, "완료", "available()는 (bool, 이유) 튜플로")
    lines = g.read_text(encoding="utf-8").splitlines()
    assert lines[-1].startswith("- ") and "[완료]" in lines[-1] and "튜플" in lines[-1]
    assert agents.guide_for("guide 태그 없는 과제") == ("", "")


def test_guide_tasks_first(tmp_path, monkeypatch):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] (agent) 스스로 만든 과제\n- [ ] (agent) [p-0123456789|수집] 수락된 제안\n"
                    "- [ ] (agent) [guide:img2threejs] 1단계\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TODO", todo)
    assert agents.next_task().startswith("[guide:img2threejs]")


def test_failure_summary_keeps_only_failures():
    out = ("....F.\nfastapi/testclient.py:1: StarletteDeprecationWarning: Using httpx is deprecated\n"
           "E       AssertionError: assert 200 == 503\n"
           "FAILED backend/tests/test_core.py::test_engine_unavailable - AssertionError: assert 200 == 503\n"
           "1 failed, 5 passed\n")
    s = agents.failure_summary({"test_output": out, "security": []})
    assert "test_engine_unavailable" in s and "200 == 503" in s and "Deprecation" not in s
    assert agents.failure_summary({"test_output": "", "security": ["위험 함수 사용: eval"]}).endswith("eval']")


def test_retry_held_once(tmp_path, monkeypatch):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] (agent:보류) 큰 과제 — 테스트 실패\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TODO", todo)
    assert agents.retry_held() and agents.next_task() == "큰 과제 (재시도)"
    agents.mark_task("큰 과제 (재시도)", False, "또 실패")
    assert not agents.retry_held()  # 두 번째 보류는 다시 열지 않음 → 사람이 봄


def test_repo_map_lists_functions(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def f():\n    pass\nclass K:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(agents, "ROOT", tmp_path)
    monkeypatch.setattr(agents, "EDITABLE", {"a.py", "missing.py"})
    assert agents.repo_map() == "a.py: f, K"


def test_llm_temperature_passed(monkeypatch):
    import core
    seen = {}
    monkeypatch.setattr(core, "LLM_API_KEY", "x")
    monkeypatch.setattr(core, "_consume_llm_budget", lambda: None)
    monkeypatch.setattr(core, "_llm_call", lambda *a, **k: seen.update(k) or "ok")
    assert core.llm("p", temperature=0.15) == "ok" and seen["temperature"] == 0.15


def test_reset_removes_new_file_after_intent_to_add(tmp_path, monkeypatch):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path)
    (tmp_path / "old.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "old.py"], cwd=tmp_path)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path)
    monkeypatch.setattr(agents, "ROOT", tmp_path)
    (tmp_path / "new.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "old.py").write_text("x = 99\n", encoding="utf-8")
    agents.sh("git", "add", "-N", "new.py")  # diff 에 보이게 했던 상태
    agents.reset_files({"old.py", "new.py"})
    assert not (tmp_path / "new.py").exists()  # 다음 시도가 새로 만들 수 있게 지워짐
    assert (tmp_path / "old.py").read_text(encoding="utf-8") == "x = 1\n"


def test_ai_errors_leave_task_open(tmp_path, monkeypatch):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] (agent) 과제 A\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TODO", todo)
    monkeypatch.setattr(agents, "queue_manager_tasks", lambda: [])
    monkeypatch.setattr(agents, "reset_files", lambda f: None)
    monkeypatch.setattr(agents, "files_for", lambda t: {"core.py"})
    rec = []
    monkeypatch.setattr(agents, "record_target_run", lambda t, r, m: rec.append(r))

    def boom(task, feedback):
        raise RuntimeError("groq: 413 Request too large")
    monkeypatch.setattr(agents, "coder", boom)
    agents.main()
    assert rec == ["ai_error"]
    assert "- [ ] (agent) 과제 A" in todo.read_text(encoding="utf-8")  # 보류로 바뀌지 않음


def test_new_file_created_even_with_search_text(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "ROOT", tmp_path)
    edits = [{"file": "backend/app/services/engines.py", "search": "# placeholder", "replace": "X = 1\n"}]
    assert agents.apply_edits(edits, {"backend/app/services/engines.py"}) == []
    assert (tmp_path / "backend/app/services/engines.py").read_text(encoding="utf-8") == "X = 1\n"


def test_mobile_quick_nav_html_present():
    import app
    with open(app.__file__, "r", encoding="utf-8") as f:
        content = f.read()
    assert "mobile-quick-nav" in content
    assert "🏠" in content and "📰" in content and "🛠" in content
    assert "position: fixed;" in content
    assert "bottom: 0;" in content


def test_block_marker_leak_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "ROOT", tmp_path)
    (tmp_path / "t.py").write_text("a = 1\n", encoding="utf-8")
    bad = [{"file": "t.py", "search": "a = 1", "replace": "a = 2\n===\nb = 3"}]
    probs = agents.apply_edits(bad, {"t.py"})
    assert probs and "형식 오류" in probs[0]
    assert (tmp_path / "t.py").read_text(encoding="utf-8") == "a = 1\n"  # 파일은 그대로
