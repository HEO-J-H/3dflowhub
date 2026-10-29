import selfheal


def _p(**k):
    return {"id": "p-1", "title": "x", "at": "2026-10-01", "decided_at": "2026-10-02", **k}


def test_probe_resolved():
    assert selfheal.done_reason(_p(probe_key="buttondown:a"), "", set(), [])
    assert not selfheal.done_reason(_p(probe_key="buttondown:a"), "", {"buttondown:a"}, [])


def test_agent_todo_done():
    todo = "- [x] (agent) [p-1|수집] 무언가\n"
    assert "완료" in selfheal.done_reason(_p(), todo, set(), [])
    assert not selfheal.done_reason(_p(), "- [ ] (agent) [p-1|수집] 무언가\n", set(), [])


def test_pr_merged(monkeypatch):
    monkeypatch.setattr(selfheal, "_pr_state", lambda repo, n: "merged" if n == 17 else "open")
    assert "#17" in selfheal.done_reason(_p(site="pix2poly", title="PR #17 검토"), "", set(), [])
    assert not selfheal.done_reason(_p(site="pix2poly", title="PR #18 검토"), "", set(), [])


def test_promo_posted_after_decision():
    p = _p(site="life-after-60", title="네이버 블로그 홍보 게시")
    assert selfheal.done_reason(p, "", set(), [{"site": "life-after-60", "at": "2026-10-05"}])
    assert not selfheal.done_reason(p, "", set(), [{"site": "life-after-60", "at": "2026-09-01"}])
    assert not selfheal.done_reason(p, "", set(), [{"site": "3dflowhub", "at": "2026-10-05"}])


def test_visitor_report_not_auto_closed():
    assert not selfheal.done_reason(_p(probe_key="report:abc"), "", set(), [])


def test_reports_become_todo(tmp_path, monkeypatch):
    import manager
    monkeypatch.setattr(manager, "PROPOSALS_PATH", tmp_path / "p.json")
    monkeypatch.setattr(selfheal, "LOG_PATH", tmp_path / "l.json")
    monkeypatch.setattr(selfheal.core, "ROOT", tmp_path)
    (tmp_path / "memory").mkdir()
    selfheal.core._save_json(tmp_path / "memory" / "reports.json", {"items": [
        {"path": "report/0/3dflowhub/p/x.html", "title": "내용이 틀려요 — 메뉴 이름", "count": 1}]})
    assert selfheal.reports_to_todo() == ["방문자 오류 제보: 내용이 틀려요"]
    assert selfheal.reports_to_todo() == []          # 같은 제보는 한 번만
    todo = manager.manual_todo()
    assert todo and "heo-j-h.github.io/3dflowhub/p/x.html" in todo[0]["proposal"]
