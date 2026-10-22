import core
import site_manager


def test_waits_when_news_budget_needed(monkeypatch, tmp_path):
    monkeypatch.setattr(site_manager, "report_path", lambda s: tmp_path / f"{s}.json")
    monkeypatch.setattr(core, "background_ok", lambda need=1: False)
    called = []
    monkeypatch.setattr(core, "llm", lambda *a, **k: called.append(1) or "{}")
    assert site_manager.review("pix2poly") is None and called == []  # 뉴스 몫을 남겨야 하면 AI 안 씀


def test_review_posts_site_proposals_and_answers(monkeypatch, tmp_path):
    monkeypatch.setattr(site_manager, "report_path", lambda s: tmp_path / f"{s}.json")
    monkeypatch.setattr(core, "background_ok", lambda need=1: True)
    monkeypatch.setattr(site_manager, "_context", lambda s: {"site": {}})
    import manager
    posted = []
    monkeypatch.setattr(manager, "_append", lambda *e: posted.extend(e))
    monkeypatch.setattr(manager, "similar_open", lambda t, s: False)
    site_manager.send_message("life-after-60", "요즘 어때?")
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"summary":"정상","proposals":[{"title":"깨진 링크 정리","category":"사이트·UX"}],'
                                                     '"replies":[{"i":0,"text":"괜찮아요"}],"watch":"링크"}')
    rep = site_manager.review("life-after-60")
    assert rep["summary"] == "정상" and posted[0]["site"] == "life-after-60" and posted[0]["by"].endswith("관리자")
    assert site_manager.messages("life-after-60")[0]["reply"] == "괜찮아요"
    assert not site_manager.due("life-after-60")  # 하루 1회
