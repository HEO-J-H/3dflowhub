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


def test_single_section_ad_placement(monkeypatch):
    monkeypatch.setattr(core, "AD_HTML", "<b>AD</b>")
    single_item = {**ITEM, "sections": [{"heading": "Only", "body": "Body"}]}
    out = core.build_post_html(single_item)
    # 섹션이 1개뿐일 때, 중간 광고(middle)가 본문(part_2 / source 앞) 뒤에 한 번만 들어가므로 <b>AD</b>는 총 3번(top, middle, bottom) 포함됨
    assert out.count("<b>AD</b>") == 3
    # top은 본문 앞에, middle은 유일한 섹션 뒤(또는 본문 뒤), bottom은 맨 아래
    assert out.index("flowhub-ad-top") < out.index("Only") < out.index("flowhub-ad-middle") < out.index("원문")


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


def test_summarize_tags_string_normalization(monkeypatch):
    monkeypatch.setattr(core, "fetch_article", lambda url: ("본문 텍스트 충분히 길게 작성하여 통과하도록 함 " * 10, {"image": "", "video": ""}))
    monkeypatch.setattr(core, "llm", lambda *args, **kwargs: '{"title_ko": "제목", "domain": "VFX", "category": "시뮬레이션", "tags": "tag1, tag2 , tag3", "summary": "요약", "insight": "코멘트", "sections": [{"heading": "H1", "body": "B1"}]}')
    res = core.summarize({"title": "T", "url": "https://example.com/t", "hint_domain": "VFX", "rss_summary": ""})
    assert res["tags"] == ["tag1", "tag2", "tag3"]


def test_draft_header_roundtrip(tmp_path, monkeypatch):
    import tistory_publisher as tp
    monkeypatch.setattr(core, "DRAFT_DIR", tmp_path)
    item = {**ITEM, "category": "제작 사례", "notion_id": "abc123"}
    path = core._save_draft_file(item, "<p>x</p>")
    post = tp.parse_draft(__import__("pathlib").Path(path))
    assert post["title"] == "제목" and post["tags"] == ["a"]
    assert post["category"] == ("VFX", "제작 사례") and post["notion_id"] == "abc123"
    assert post["html"] == "<p>x</p>"


def test_merge_removes_seed_and_moves_counts(tmp_path, monkeypatch):
    import evolve
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "m.json")
    core.register_category("VFX", "시뮬레이션")
    core.register_category("VFX", "Houdini 시뮬레이션")
    evolve.apply_merge("VFX", "시뮬레이션", "Houdini 시뮬레이션")
    cats = core.load_categories()["VFX"]
    assert "시뮬레이션" not in cats and "Houdini 시뮬레이션" in cats
    assert core.load_memory()["category_counts"]["VFX/Houdini 시뮬레이션"] == 2


def test_strategy_blocks_dead_feed_and_rejects_bad_suggestion(tmp_path, monkeypatch):
    import evolve
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "m.json")
    core._save_json(core.MEMORY_PATH, {"runs": [], "feed_health": {"https://dead/feed": 3}})
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"lesson": "x", "prompt_notes": ["n1"], '
                        '"keyword_hints": {"VFX": ["houdini"]}, "feed_suggestions": [{"domain": "VFX", "url": "https://fake"}]}')
    monkeypatch.setattr(evolve, "feed_ok", lambda url, **k: False)
    st = evolve.update_strategy({"prompt_notes": [], "keyword_hints": {}, "extra_feeds": {}, "blocked_feeds": [], "history": []})
    assert "https://dead/feed" in st["blocked_feeds"] and st["prompt_notes"] == ["n1"]
    assert st["keyword_hints"]["VFX"] == ["houdini"] and not st["extra_feeds"]


def test_post_html_faq_and_related():
    item = {**ITEM, "faq": [{"q": "무료인가요?", "a": "네."}],
            "related": [{"url": "https://hjh1014.tistory.com/3", "title": "관련글"}]}
    out = core.build_post_html(item)
    assert "자주 묻는 질문" in out and "Q. 무료인가요?" in out
    assert "함께 보면 좋은 글" in out and 'href="https://hjh1014.tistory.com/3"' in out


def test_pick_by_weights_prefers_heavy_domain():
    cands = [{"hint_domain": d, "url": f"{d}{i}"} for d in ("VFX", "AI 3D") for i in range(10)]
    picked = core.pick_by_weights(cands, ["VFX", "AI 3D"], 10, {"VFX": 0.8, "AI 3D": 0.2})
    assert sum(c["hint_domain"] == "VFX" for c in picked) == 8 and len(picked) == 10


def test_domain_weights_need_samples_and_keep_floor():
    import evolve
    few = {"by_group": {"VFX": {"posts": 2, "avg": 50}}}
    assert set(evolve.learn_domain_weights(few, {}).values()) == {0.25}
    many = {"by_group": {"VFX": {"posts": 6, "avg": 90}, "AI 3D": {"posts": 4, "avg": 10},
                         "3D DCC": {"posts": 1, "avg": 0}, "Game Engine": {"posts": 1, "avg": 0}}}
    w = evolve.learn_domain_weights(many, {})
    assert w["VFX"] > w["AI 3D"] > 0 and min(w.values()) >= 0.15


def test_simhash_detects_same_story_different_outlet():
    a = core.title_simhash("Epic Games releases Unreal Engine 5.8 with new PCG tools - 80 Level")
    b = core.title_simhash("Epic Games releases Unreal Engine 5.8 with new PCG tools")
    c = core.title_simhash("Blender 5.3 beta adds built-in Loop Tools")
    assert core.is_near_duplicate(a, [b]) and not core.is_near_duplicate(c, [a])


def test_strategy_survives_malformed_llm_json(tmp_path, monkeypatch):
    import evolve
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "m.json")
    monkeypatch.setattr(evolve, "performance_table", lambda: {})
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"prompt_notes": null, "keyword_hints": {"VFX": "houdini"}, '
                        '"feed_suggestions": ["x"], "lesson": null}')
    st = evolve.update_strategy({"prompt_notes": [], "keyword_hints": {}, "extra_feeds": {}, "blocked_feeds": [],
                                 "history": []})
    assert st["keyword_hints"] == {} and "strategy_updated_at" in st


def test_merge_cycle_does_not_hide_both(tmp_path, monkeypatch):
    import evolve
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "m.json")
    core.register_category("VFX", "A분류")
    core.register_category("VFX", "B분류")
    evolve.apply_merge("VFX", "A분류", "B분류")
    evolve.apply_merge("VFX", "B분류", "A분류")
    cats = core.load_categories()["VFX"]
    assert "A분류" in cats and "B분류" not in cats


def test_normalize_summary_coerces_shapes():
    d = core.normalize_summary({"sections": ["본문만"], "category": ["X"], "domain": "?"}, {**ITEM, "hint_domain": "VFX"})
    assert d["sections"] == [{"heading": "내용", "body": "본문만"}] and d["category"] == "X"
    assert d["title_ko"] == "Src" and d["domain"] == "VFX"


def test_category_index_stays_within_domain():
    import tistory_publisher as tp
    labels = ["카테고리 없음", "3D DCC", "- 튜토리얼", "Game Engine", "- 엔진 업데이트", "- 튜토리얼"]
    assert tp.pick_category_index(labels, "Game Engine", "튜토리얼") == 5
    assert tp.pick_category_index(labels, "3D DCC", "튜토리얼") == 2
    assert tp.pick_category_index(labels, "Game Engine", "없는분류") == 3
    assert tp.pick_category_index(labels, "VFX", "x") == -1


def test_merge_json_unions_lists_and_keeps_max():
    a = {"runs": [{"at": 1}], "cnt": {"x": 2}, "lessons": ["a"]}
    b = {"runs": [{"at": 1}, {"at": 2}], "cnt": {"x": 5, "y": 1}, "lessons": ["b"]}
    m = core.merge_json(a, b)
    assert m["runs"] == [{"at": 1}, {"at": 2}] and m["cnt"] == {"x": 5, "y": 1} and m["lessons"] == ["a", "b"]


def test_offtopic_article_is_skipped(monkeypatch):
    monkeypatch.setattr(core, "fetch_article", lambda url: ("x" * 300, {"image": "", "video": ""}))
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"title_ko": "날씨", "relevance": 1, '
                        '"sections": [{"heading": "h", "body": "b"}]}')
    assert core.summarize({"title": "Weather", "url": "https://ex.com/w", "hint_domain": "VFX", "rss_summary": ""}) is None


def test_llm_budget_blocks_after_limit(monkeypatch):
    core._save_json(core.CONFIG_PATH, {"llm_daily_budget": 2})
    monkeypatch.setattr(core, "LLM_API_KEY", "k")

    class R:
        ok, status_code, headers = True, 200, {}
        def json(self): return {"choices": [{"message": {"content": "hi"}}]}
    monkeypatch.setattr(core.requests, "post", lambda *a, **k: R())
    assert core.llm("a") == "hi" and core.llm("b") == "hi"
    import pytest
    with pytest.raises(core.LLMBudgetExceeded):
        core.llm("c")
    assert core.llm_usage_today() == 2
