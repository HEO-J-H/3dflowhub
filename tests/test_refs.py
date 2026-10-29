import refs


def test_fix_needs_steps(monkeypatch):
    monkeypatch.setattr(refs, "_ask", lambda p, t=1800: {"summary": "s", "causes": ["c"], "steps": ["a", "b", "c"]})
    p = refs.make_fix("Blender", "KeyError: x", "제목", None)
    assert p and p["steps"] == ["a", "b", "c"] and p["verified"] is None
    monkeypatch.setattr(refs, "_ask", lambda p, t=1800: {"summary": "s"})
    assert refs.make_fix("Blender", "KeyError: x", "제목", None) is None


def test_change_needs_source(monkeypatch):
    monkeypatch.setattr(refs, "page_text", lambda u: "짧음")
    assert refs.make_change("Blender", "9.9", "https://example.com/") is None


def test_verify_marks_only_real_repro(tmp_path, monkeypatch):
    monkeypatch.setattr(refs, "FIX_DIR", tmp_path)
    p = {"id": "a", "error": "KeyError: 'x'", "title": "t", "repro": {"bad": "bad", "good": "good"}, "verified": None}
    refs.core._save_json(tmp_path / "a.json", p)
    results = {"bad": (False, "Traceback\nKeyError: 'x'"), "good": (True, "")}
    monkeypatch.setattr(refs, "run_repro", lambda code, timeout=120: results[code])
    refs.verify_fixes()
    assert refs.load("fix")[0]["verified"] is True
    p["verified"] = None
    refs.core._save_json(tmp_path / "a.json", p)
    results["bad"] = (False, "Traceback\nNameError: y")   # 다른 오류로 실패 → 재현 아님
    refs.verify_fixes()
    assert refs.load("fix")[0]["verified"] is False
