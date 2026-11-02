import core
import scorecard


def test_gaps_and_tune_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(scorecard, "TUNING_PATH", tmp_path / "t.json")
    monkeypatch.setattr(core, "background_ok", lambda n=1: True)
    score = {"at": "x", "post_image_pct": 40, "ref_visual_pct": 99, "thin_pct": 20, "manual_coverage_pct": 1,
             "compare_coverage_pct": 100}
    names = [g["metric"] for g in scorecard.gaps(score)]
    assert "post_image_pct" in names and "thin_pct" in names and "compare_coverage_pct" not in names
    for _ in range(20):
        scorecard.tune(score)
    assert scorecard.knob("visuals_posts_per_run") == scorecard.KNOBS["visuals_posts_per_run"][2]  # 상한에서 멈춤
    assert scorecard.knob("compare_daily") == scorecard.KNOBS["compare_daily"][0]  # 목표 달성 → 기본값


def test_site_menu_hides_empty_and_reorders(monkeypatch):
    import build_site
    monkeypatch.setattr(build_site, "_MENU_CACHE", None)
    monkeypatch.setattr(build_site, "section_count", lambda u: 0 if u == "compare/" else None)
    monkeypatch.setattr(core, "load_config", lambda: {"site_menu": {"group_order": ["자료"], "order": {"배우기": ["guide/"]},
                                                                      "desc": {"fix/": "새 설명"}}})
    m = build_site.site_menu()
    assert m[0][0] == "자료"
    learn = dict(m)["배우기"]
    assert learn[0][0] == "guide/" and all(u != "compare/" for u, *_ in learn)
    assert dict(m)["문제 해결"][0][3] == "새 설명"


def test_manager_site_menu_action_validated():
    import manager
    ok = manager._valid_action({"type": "site_menu", "order": {"배우기": ["guide/", "evil/"]}, "desc": {"x/": "y"}})
    assert ok and ok["order"]["배우기"] == ["guide/"] and ok["desc"] == {}
    assert manager._valid_action({"type": "site_menu", "order": {"없는묶음": ["learn/"]}}) is None
