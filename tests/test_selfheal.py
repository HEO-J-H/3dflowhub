from datetime import datetime, timedelta, timezone

import agents
import core
import manager
import selfheal


def _paths(tmp_path, monkeypatch):
    monkeypatch.setattr(selfheal, "TESTS_PATH", tmp_path / "tests_status.json")
    monkeypatch.setattr(selfheal, "LOG_PATH", tmp_path / "selfheal.json")


def test_record_tests_keeps_last_ok_time(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    ok = selfheal.record_tests(0, str(tmp_path / "none.log"))
    bad = selfheal.record_tests(1, str(tmp_path / "none.log"))
    assert ok["ok"] and not bad["ok"] and bad["ok_at"] == ok["ok_at"]


def test_diagnose_tests_then_stall_then_ok(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    core._save_json(selfheal.TESTS_PATH, {"ok": False, "ok_at": "2026-10-24T11:00:00+00:00"})
    assert selfheal.diagnose(now)[0] == "tests"
    core._save_json(selfheal.TESTS_PATH, {"ok": True})
    core._save_json(core.MEMORY_PATH, {"runs": [{"at": (now - timedelta(hours=3)).isoformat()}]})
    assert selfheal.diagnose(now)[0] == "stall"
    core._save_json(core.MEMORY_PATH, {"runs": [{"at": (now - timedelta(minutes=5)).isoformat()}]})
    assert selfheal.diagnose(now) == ("", None)


def test_heal_without_agent_commits_only_logs(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    core._save_json(selfheal.TESTS_PATH, {"ok": False, "ok_at": ""})
    monkeypatch.setattr(selfheal, "agent_commits", lambda since: [])
    assert "대상 없음" in selfheal.heal()
    assert core._load_json(selfheal.LOG_PATH, [])[-1]["ok"] is False


def test_probe_flags_missing_newsletter(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ROOT", tmp_path)
    core._save_json(tmp_path / "config.json", {"newsletter_buttondown": "nobody"})

    class R:
        status_code = 404
    monkeypatch.setattr(selfheal.requests, "get", lambda *a, **k: R())
    issues = selfheal.probe()
    assert issues and issues[0]["key"] == "buttondown:nobody"


def test_report_issues_once(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "PROPOSALS_PATH", tmp_path / "proposals.json")
    it = [{"key": "k1", "title": "고장", "how": "이렇게"}]
    assert selfheal.report_issues(it) == ["고장"]
    assert selfheal.report_issues(it) == []
    assert manager.manual_todo()[0]["probe_key"] == "k1"


def test_triage_closes_done_and_notes_human(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "PROPOSALS_PATH", tmp_path / "proposals.json")
    monkeypatch.setattr(core, "background_ok", lambda n=1: True)
    monkeypatch.setattr(selfheal, "_context_for", lambda site: "")
    manager._append({"at": "1", "kind": "proposal", "id": "a", "title": "이미 한 일", "action": None},
                    {"at": "1", "kind": "decision", "id": "a", "v": "accepted"},
                    {"at": "2", "kind": "proposal", "id": "b", "title": "키 발급", "action": None},
                    {"at": "2", "kind": "decision", "id": "b", "v": "accepted"})
    answers = {"이미 한 일": {"verdict": "done_already", "reason": "커밋 있음"},
               "키 발급": {"verdict": "human", "reason": "로그인 필요", "how": "사이트에서 발급"}}
    monkeypatch.setattr(selfheal, "classify", lambda p, ctx: answers[p["title"]])
    assert len(selfheal.triage()) == 2
    st = {p["id"]: p for p in manager.board()["proposals"]}
    assert st["a"]["status"] == "done" and st["b"]["status"] == "accepted" and "사이트에서 발급" in st["b"]["applied"]
    assert selfheal.triage() == []  # 한 번 분류한 일은 다시 묻지 않음


def test_repeat_guard(tmp_path, monkeypatch):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [x] (agent) collect(): 빈 피드 기록\n- [ ] (agent) collect(): 빈 피드 기록 (재시도)\n"
                    "- [ ] (agent) build(): 새 일\n", encoding="utf-8")
    monkeypatch.setattr(agents, "TODO", todo)
    monkeypatch.setattr(agents, "__file__", str(tmp_path / "agents.py"))
    assert agents.repeat_guard("collect(): 빈 피드 기록 (재시도)").startswith("done:")
    assert agents.repeat_guard("build(): 새 일") == ""
    runs = tmp_path / "memory" / "sites" / agents.SITE / "agent_runs.json"
    runs.parent.mkdir(parents=True)
    core._save_json(runs, [{"task": "build(): 새 일", "result": "held", "msg": "x"}] * 2)
    assert agents.repeat_guard("build(): 새 일").startswith("held:")
