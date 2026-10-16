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
    assert w["VFX"] > w["AI 3D"] > 0 and min(w.values()) >= 0.1 and abs(sum(w.values()) - 1) < 0.01


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
    b = {"runs": [{"at": 1}, {"at": 2}], "cnt": {"x": 5, "y": 1}, "lessons": ["a", "b"]}
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


def test_merge_json_remote_wins_and_no_resurrection():
    remote = {"runs": [2, 3, 4], "state": {"last_run": "2026-10-16T05:00:00"}, "blocked": ["b"], "name": "remote"}
    local = {"runs": [1, 2, 3, 9], "state": {"last_run": "2026-10-16T04:00:00"}, "blocked": ["a", "b"], "name": "local"}
    m = core.merge_json(remote, local)
    assert m["runs"] == [2, 3, 4, 9]          # 원격이 잘라낸 1 은 되살아나지 않고, 로컬 새 항목 9 만 추가
    assert m["state"]["last_run"] == "2026-10-16T05:00:00" and m["name"] == "remote"
    assert m["blocked"] == ["b"]              # 원격에서 제거된 a 는 복구 안 됨


def test_llm_usage_sums_sources():
    day = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    core._save_json(core.LLM_USAGE_PATH, {day: {"ci": 30, "local": 5}})
    assert core.llm_usage_today() == 35
    merged = core.merge_json({day: {"ci": 40}}, {day: {"ci": 30, "local": 7}})
    assert merged[day] == {"ci": 40, "local": 7}


def test_ci_commit_merges_concurrent_memory(tmp_path, monkeypatch):
    import subprocess

    def git(cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(remote), str(seed))
    for c in (seed,):
        git(c, "config", "user.email", "t@t"); git(c, "config", "user.name", "t")
    (seed / "memory").mkdir()
    core._save_json(seed / "memory" / "m.json", {"runs": [1], "n": 1})
    (seed / "TODO.md").write_text("- [x] done\n")
    git(seed, "add", "-A"); git(seed, "commit", "-qm", "init"); git(seed, "push", "-q", "origin", "main")

    ci = tmp_path / "ci"
    git(tmp_path, "clone", "-q", str(remote), str(ci))
    git(ci, "config", "user.email", "t@t"); git(ci, "config", "user.name", "t")
    # 다른 실행이 먼저 push
    core._save_json(seed / "memory" / "m.json", {"runs": [1, 2], "n": 5})
    git(seed, "commit", "-qam", "other"); git(seed, "push", "-q", "origin", "main")
    # 이번 실행: 오래된 checkout 에서 memory 변경 + 새 글
    core._save_json(ci / "memory" / "m.json", {"runs": [1, 3], "n": 2})
    (ci / "content").mkdir(); (ci / "content" / "p.json").write_text("{}")
    monkeypatch.setattr(core, "ROOT", ci)
    assert core.ci_commit(["memory/", "content/", "TODO.md"], "run") is True
    final = tmp_path / "final"
    git(tmp_path, "clone", "-q", str(remote), str(final))
    m = core._load_json(final / "memory" / "m.json", {})
    assert m == {"runs": [1, 2, 3], "n": 5} and (final / "content" / "p.json").exists()
    assert (final / "TODO.md").read_text() == "- [x] done\n"


def test_site_head_scripts_only_with_valid_ids():
    import build_site
    core._save_json(core.CONFIG_PATH, {"goatcounter_code": "3dflowhub", "adsense_client": "ca-pub-1234567890123456"})
    h = build_site.head_scripts()
    assert "3dflowhub.goatcounter.com/count" in h and "client=ca-pub-1234567890123456" in h
    core._save_json(core.CONFIG_PATH, {"goatcounter_code": "x\"><script>", "adsense_client": "bad"})
    assert build_site.head_scripts() == ""  # 잘못된 값은 삽입하지 않음 (스크립트 주입 방지)


def test_custom_domain_is_applied_and_used_in_prompt(monkeypatch):
    monkeypatch.setattr(core, "DOMAINS", dict(core.DOMAINS))
    monkeypatch.setattr(core, "DOMAIN_META", dict(core.DOMAIN_META))
    monkeypatch.setattr(core, "SEED_CATEGORIES", dict(core.SEED_CATEGORIES))
    added = core.apply_custom_domains({"custom_domains": {
        "3D 프린팅": {"seeds": ["Bambu Lab"], "feeds": ["https://ex.com/feed", "bad"], "icon": "🖨️", "about": "3D printing"},
        "VFX": {"seeds": ["x"]}}})  # 기본 분야 덮어쓰기는 무시
    assert added == ["3D 프린팅"] and core.DOMAINS["3D 프린팅"]["feeds"] == ["https://ex.com/feed"]
    assert core.DOMAIN_META["3D 프린팅"]["slug"].startswith("x-") and "3D printing" in core.domain_topics()
    assert core.DOMAINS["VFX"]["seeds"] != ["x"]


def test_notion_off_uses_github_data(monkeypatch):
    core._save_json(core.CONFIG_PATH, {"save_notion": False})
    monkeypatch.setattr(core, "NOTION_TOKEN", "x")
    assert core._notion() is None
    core._save_json(core.POSTS_DIR / "2026-10-16-a.json", {"title_ko": "가", "url": "https://ex.com/a", "domain": "VFX",
                                                           "category": "컴포지팅", "collected_at": "2026-10-16"})
    rows = core.fetch_dashboard_rows()
    assert rows[0]["제목"] == "가" and rows[0]["사이트"].endswith("/p/2026-10-16-a.html")
    rel = core.related_posts(None, {"url": "https://ex.com/b", "domain": "VFX", "category": "컴포지팅"})
    assert rel and rel[0]["url"].startswith(core.SITE_URL)


def test_save_config_keeps_other_keys():
    core.save_config({"goatcounter_code": "3dflowhub", "custom_domains": {"X": {}}})
    core.save_config({"interval": "계속"})
    c = core._load_json(core.CONFIG_PATH, {})
    assert c["goatcounter_code"] == "3dflowhub" and "X" in c["custom_domains"] and c["interval"] == "계속"


def test_domain_weights_stay_positive_with_many_domains(monkeypatch):
    import evolve
    doms = {f"D{i}": {} for i in range(9)}
    monkeypatch.setattr(core, "DOMAINS", doms)
    perf = {"by_group": {d: {"posts": 2, "avg": (i + 1) * 10} for i, d in enumerate(doms)}}
    w = evolve.learn_domain_weights(perf, {})
    assert min(w.values()) > 0 and w["D8"] > w["D0"] and abs(sum(w.values()) - 1) < 0.01


def test_empty_domain_selection_collects_nothing():
    stats = core.run_pipeline(3, [], publish=False)
    assert stats["collected"] == 0 and "no domains selected" in stats["errors"]


def test_generate_keywords_cross_domain_deduplication(monkeypatch):
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"keywords": ["Blender 4.3", "Duplicate KW"]}')
    kws = core.generate_keywords(["3D DCC", "Game Engine"], per_domain=2)
    all_kws = [k.lower() for vals in kws.values() for k in vals]
    assert len(all_kws) == len(set(all_kws)), f"Keywords contain cross-domain duplicates: {kws}"


def test_opro_trajectory_scores_and_keeps_notes_until_evaluated(monkeypatch):
    import evolve
    runs = [{"strategy_ver": "a", "collected": 10, "saved": 9}, {"strategy_ver": "b", "collected": 10, "saved": 4,
                                                                  "offtopic": 4}]
    t = evolve.score_trajectory(runs, {"a": ["n1"], "b": ["n2"]})
    assert [x["ver"] for x in t] == ["b", "a"] and t[-1]["score"] == 0.9
    monkeypatch.setattr(evolve, "performance_table", lambda: {})
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"prompt_notes": ["new"], "lesson": "x"}')
    st = {"prompt_notes": ["old"], "keyword_hints": {}, "extra_feeds": {}, "blocked_feeds": [], "history": []}
    st = evolve.update_strategy(st)
    assert st["prompt_notes"] == ["old"]  # 현재 가이드 실행 기록 0회 → 교체 보류
    ver = core.strategy_version(["old"])
    core._save_json(core.MEMORY_PATH, {"runs": [{"strategy_ver": ver, "collected": 3, "saved": 1}] * 3})
    st = evolve.update_strategy(st)
    assert st["prompt_notes"] == ["new"]


def test_strategy_due_is_adaptive():
    import evolve
    from datetime import datetime, timedelta, timezone
    ago = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    st = {"prompt_notes": ["n"], "strategy_updated_at": ago(2)}
    ver = core.strategy_version(["n"])
    core._save_json(core.MEMORY_PATH, {"runs": [{"strategy_ver": ver, "collected": 3}] * 3})
    assert evolve.strategy_due(st) is False          # 2시간, 표본 9건 < 15
    core._save_json(core.MEMORY_PATH, {"runs": [{"strategy_ver": ver, "collected": 5}] * 3})
    assert evolve.strategy_due(st) is True           # 표본 15건 충족 → 6시간 안 기다림
    assert evolve.strategy_due({**st, "strategy_updated_at": ago(0.5)}) is False  # 최소 1시간 간격
    assert evolve.strategy_due({**st, "strategy_updated_at": ago(7)}) is True


def test_interleave_by_source_breaks_single_site_dominance():
    c = [{"hint_domain": "3D DCC", "source": "blendernation.com", "t": i} for i in range(3)] + \
        [{"hint_domain": "3D DCC", "source": "reddit.com", "t": 9}]
    out = core.interleave_by_source(c)
    assert [x["source"] for x in out[:2]] == ["blendernation.com", "reddit.com"]


def test_topic_is_normalized_to_fixed_types():
    d = core.normalize_summary({"sections": ["x"], "category": "Blender", "topic": "튜토리얼·팁"}, {**ITEM, "hint_domain": "3D DCC"})
    assert d["topic"] == "튜토리얼·팁" and d["category"] == "Blender"
    d = core.normalize_summary({"sections": ["x"], "topic": "아무거나"}, {**ITEM, "hint_domain": "3D DCC"})
    assert d["topic"] == core.DEFAULT_TOPIC


def test_tool_names_follow_merges_and_reject_topics():
    core.register_category("Game Engine", "Unreal Engine")
    m = core.load_memory(); m["category_merges"] = {"Game Engine/UE5": "Unreal Engine"}; core._save_json(core.MEMORY_PATH, m)
    assert core.register_category("Game Engine", "UE5") == "Unreal Engine"
    assert core.register_category("Game Engine", "튜토리얼·팁") == "기타 엔진"   # 유형 이름은 도구 불가 → 기타
    assert core.register_category("3D DCC", "Substance 3D/Painter") == "Substance 3D·Painter"


def test_topic_chips_use_root_relative_links(tmp_path, monkeypatch):
    import build_site
    monkeypatch.setattr(build_site, "OUT", tmp_path / "site")
    for i in range(35):  # 페이지네이션(30개) 발생
        core._save_json(core.POSTS_DIR / f"2026-10-16-{i:03d}.json", {"title_ko": f"t{i}", "url": f"https://e/{i}",
                        "domain": "3D DCC", "category": "Blender", "topic": "튜토리얼·팁", "collected_at": f"2026-10-16T00:{i:02d}"})
    build_site.build()
    html2 = (tmp_path / "site" / "c" / "3d-dcc" / "blender" / "page" / "2" / "index.html").read_text(encoding="utf-8")
    assert 'href="../../../../../c/3d-dcc/blender/tutorial/"' in html2


def test_glossary_fixes_transliterated_tool_names():
    assert core.fix_terms("맥로스크립트로 3DS 맥스 자동화") == "MacroScript로 3ds Max 자동화"
    assert core.fix_terms("블렌더(Blender) 지오메트리 노드") == "Blender Geometry Nodes"
    assert core.fix_terms("맥스 스크립트") == "MAXScript"
    d = core.apply_glossary({"title_ko": "블렌더 튜토리얼", "summary": "", "tags": ["블렌더"], "sections": [], "faq": []})
    assert d["title_ko"] == "Blender 튜토리얼" and "블렌더" in d["tags"] and "Blender" in d["tags"]


def test_user_glossary_from_config():
    core._save_json(core.CONFIG_PATH, {"glossary": {"RailClone": "레일클론|레일 클론"}})
    assert core.fix_terms("레일 클론 플러그인") == "RailClone 플러그인"


def test_learned_glossary_matches_whole_words_only():
    core._save_json(core.MEMORY_PATH, {"glossary_learned": {"메타휴먼": "MetaHuman", "스타": "Star"}})
    assert core.fix_terms("메타휴먼을 활용") == "MetaHuman을 활용"
    assert core.fix_terms("스타일라이즈드 셰이딩") == "스타일라이즈드 셰이딩"   # 다른 단어 훼손 없음
    assert core.fix_terms("스타 개발자") == "Star 개발자"


def test_audit_terms_filters_fragments_and_brands(monkeypatch):
    import evolve
    core._save_json(core.POSTS_DIR / "2026-10-16-x.json", {"title_ko": "스피드트리 구글 스타", "summary": "", "sections": []})
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"terms": {"스피드트리": "SpeedTree", "구글": "Google", "스타": "Star"}}')
    assert evolve.audit_terms() == {"스피드트리": "SpeedTree"}


def test_http_error_feed_is_not_counted_as_empty(monkeypatch):
    class R:
        status_code = 429
        content = b""
        def raise_for_status(self):
            raise core.requests.HTTPError("429 Too Many Requests")
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: R())
    import pytest
    with pytest.raises(core.requests.HTTPError):
        core.fetch_feed("https://www.reddit.com/r/Maxscript/.rss")
