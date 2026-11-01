import sources


def test_find_feeds_reads_link_tags(monkeypatch):
    class R:
        url = "https://example.com/"
        text = '<html><head><link rel="alternate" type="application/rss+xml" href="/blog/feed.xml"></head></html>'
    monkeypatch.setattr(sources, "_get", lambda u, timeout=15: R())
    assert sources.find_feeds("https://example.com/")[0] == "https://example.com/blog/feed.xml"


def test_check_feed_counts_textures_as_3d(monkeypatch):
    import time

    class F:
        feed = {"title": "Free CC0 PBR Textures"}
        entries = [{"title": f"Oak {i} wood texture", "summary": "", "published_parsed": time.gmtime()} for i in range(5)]
    monkeypatch.setattr(sources.core, "fetch_feed", lambda u: F())
    assert sources.check_feed("https://x/feed")["ok"]


def test_discover_adds_only_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "LOG_PATH", tmp_path / "s.json")
    saved = {}
    monkeypatch.setattr(sources.core, "load_strategy", lambda: {"extra_feeds": {}})
    monkeypatch.setattr(sources.core, "_save_json", lambda p, d: saved.__setitem__(str(p), d))
    monkeypatch.setattr(sources, "current_feeds", lambda: set())
    monkeypatch.setattr(sources, "find_feeds", lambda u: [u + "feed"])
    monkeypatch.setattr(sources, "check_feed", lambda f: {"ok": "good" in f, "items": 5, "relevant": 1, "newest_days": 1,
                                                         "title": "t", "why": "x"})
    out = sources.discover([("3D DCC", "https://good.example/"), ("3D DCC", "https://bad.example/")], use_ai=False)
    assert len(out) == 1 and "good" in out[0]
