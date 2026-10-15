from datetime import datetime, timedelta, timezone

import core

ITEM = {"title": "Src", "url": "https://example.com/a", "domain": "VFX", "summary": "요약",
        "title_ko": "제목", "tags": ["a"],
        "sections": [{"heading": f"H{i}", "body": f"B{i}"} for i in range(4)]}


def test_ads_inserted_top_middle_bottom(monkeypatch):
    monkeypatch.setattr(core, "AD_HTML", "<b>AD</b>")
    out = core.build_post_html(ITEM)
    assert out.count("<b>AD</b>") == 3
    assert out.index("flowhub-ad-top") < out.index("H0") < out.index("flowhub-ad-middle") < out.index("H2")
    assert out.rindex("flowhub-ad-bottom") > out.index("원문")


def test_no_ads_when_unconfigured(monkeypatch):
    monkeypatch.setattr(core, "AD_HTML", "")
    monkeypatch.setattr(core, "ADSENSE_CLIENT", "")
    assert "flowhub-ad" not in core.build_post_html(ITEM)


def test_html_escaped():
    out = core.build_post_html({**ITEM, "sections": [{"heading": "<script>", "body": "x"}]})
    assert "<script>" not in out.split("원문")[0].replace("adsbygoogle", "")


def test_should_run():
    now = datetime.now(timezone.utc)
    assert core.should_run({"interval": "1시간 단위"}, {"last_run": None})
    assert not core.should_run({"interval": "1시간 단위"}, {"last_run": (now - timedelta(minutes=10)).isoformat()})
    assert core.should_run({"interval": "10분 단위"}, {"last_run": (now - timedelta(minutes=10)).isoformat()})


def test_duplicate_publish_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "PUBLISHED_LOG", tmp_path / "p.json")
    monkeypatch.setattr(core, "DRAFT_DIR", tmp_path / "d")
    monkeypatch.setattr(core, "TISTORY_ACCESS_TOKEN", "")
    assert core.publish_to_tistory(ITEM)["status"] == "draft_file"
    assert core.publish_to_tistory(ITEM)["status"] == "duplicate"


def test_collect_empty_feed(monkeypatch):
    class DummyFeed:
        entries = []

    monkeypatch.setattr(core, "generate_keywords", lambda doms, **kw: {d: ["test"] for d in doms})
    monkeypatch.setattr(core.feedparser, "parse", lambda src, **kw: DummyFeed())
    monkeypatch.setattr(core, "RUN_ERRORS", [])
    
    res = core.collect(["VFX"], 5, set())
    assert res == []
    assert any("empty feed:" in err for err in core.RUN_ERRORS)


def test_extract_media_og_and_youtube():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup('<meta property="og:image" content="/img/a.jpg">'
                         '<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>', "html.parser")
    m = core.extract_media(soup, "https://ex.com/post")
    assert m == {"image": "https://ex.com/img/a.jpg", "video": "https://www.youtube.com/watch?v=abcdefghijk"}


def test_extract_media_youtube_thumbnail_fallback():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup('<a href="https://youtu.be/abcdefghijk">v</a>', "html.parser")
    assert core.extract_media(soup, "https://ex.com")["image"].endswith("/abcdefghijk/hqdefault.jpg")


def test_register_category_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "m.json")
    assert core.register_category("VFX", "시뮬레이션") == "시뮬레이션"
    assert core.register_category("VFX", "새분류") == "새분류"
    assert "새분류" in core.load_categories()["VFX"]
    monkeypatch.setattr(core, "MAX_CATEGORIES_PER_DOMAIN", 1)
    assert core.register_category("VFX", "또다른") == core.load_categories()["VFX"][0]


def test_post_html_has_media_and_category(monkeypatch):
    item = {**ITEM, "category": "제작 사례", "insight": "실무 코멘트",
            "media": {"image": "https://ex.com/a.jpg", "video": "https://www.youtube.com/watch?v=abcdefghijk"}}
    monkeypatch.setattr(core, "TISTORY_EMBED_IMAGES", True)
    out = core.build_post_html(item)
    assert '<img src="https://ex.com/a.jpg"' in out and "이미지 출처" in out and "example.com" in out
    assert "youtube.com/embed/abcdefghijk" in out and "VFX › 제작 사례" in out
    assert "에디터 코멘트" in out and "실무 코멘트" in out
    monkeypatch.setattr(core, "TISTORY_EMBED_IMAGES", False)
    assert "<img" not in core.build_post_html(item)


def test_draft_header_roundtrip(tmp_path, monkeypatch):
    import tistory_publisher as tp
    monkeypatch.setattr(core, "DRAFT_DIR", tmp_path)
    item = {**ITEM, "category": "제작 사례", "notion_id": "abc123"}
    path = core._save_draft_file(item, "<p>x</p>")
    post = tp.parse_draft(__import__("pathlib").Path(path))
    assert post["title"] == "제목" and post["tags"] == ["a"]
    assert post["category"] == ("VFX", "제작 사례") and post["notion_id"] == "abc123"
    assert post["html"] == "<p>x</p>"
