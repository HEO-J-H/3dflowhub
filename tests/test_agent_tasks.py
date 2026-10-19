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
