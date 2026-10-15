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
