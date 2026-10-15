import agents


def test_apply_edits_rejects_protected_file():
    assert agents.apply_edits([{"file": ".github/workflows/x.yml", "search": "a", "replace": "b"}])


def test_apply_edits_rejects_ambiguous_search():
    assert agents.apply_edits([{"file": "core.py", "search": "def ", "replace": "x"}])


def test_qa_flags_dangerous_and_secret(monkeypatch):
    class Done:  # 실제 pytest 재귀 실행 방지
        returncode, stdout = 0, "ok"
    monkeypatch.setattr(agents.subprocess, "run", lambda *a, **k: Done())
    r = agents.qa("+++ b/core.py\n+eval(x)\n+k='ghp_" + "a" * 36 + "'")
    assert any("eval" in s for s in r["security"]) and "비밀값 하드코딩 의심" in r["security"]
