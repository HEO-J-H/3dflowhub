import enrich


def test_paper_goes_to_rewrite_not_generic_enrich(monkeypatch):
    called = {}
    monkeypatch.setattr(enrich, "rewrite_paper", lambda p: called.setdefault("p", p) and None)
    monkeypatch.setattr(enrich, "gather", lambda p: (_ for _ in ()).throw(AssertionError("generic enrich used")))
    enrich.enrich_post({"id": "x", "url": "https://arxiv.org/abs/2610.34903", "title_ko": "t"})
    assert called["p"]["id"] == "x"
    assert enrich.is_paper({"topic": "연구·논문"}) and not enrich.is_paper({"url": "https://www.cgchannel.com/x"})


def test_rewrite_rejects_without_paper_text(monkeypatch):
    monkeypatch.setattr(enrich, "paper_source", lambda u: {"text": "short"})
    assert enrich.rewrite_paper({"id": "x", "url": "https://arxiv.org/abs/1"}) is None
