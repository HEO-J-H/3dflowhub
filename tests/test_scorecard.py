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


def test_archive_days_shrinks_when_site_big(tmp_path, monkeypatch):
    monkeypatch.setattr(scorecard, "TUNING_PATH", tmp_path / "t.json")
    monkeypatch.setattr(core, "background_ok", lambda n=1: True)
    big = {"at": "x", "site_mb": 700, "repo_mb": 100, "post_image_pct": 100, "ref_visual_pct": 100, "thin_pct": 0,
           "manual_coverage_pct": 100, "compare_coverage_pct": 100}
    for _ in range(10):
        scorecard.tune(big)
    assert scorecard.knob("archive_days") == 180  # 최소까지
    small = {**big, "site_mb": 100}
    for _ in range(10):
        scorecard.tune(small)
    assert scorecard.knob("archive_days") == 365  # 다시 기본값


def test_archived_only_old_unseen_thin():
    import build_site
    old = {"id": "a", "collected_at": "2020-01-01T00:00:00", "sections": [{"body": "짧음"}]}
    assert build_site.archived(old, {}, 365)
    assert not build_site.archived({**old, "pick": True}, {}, 365)
    assert not build_site.archived(old, {"a": {"views": 3}}, 365)
    assert not build_site.archived({**old, "collected_at": "2999-01-01"}, {}, 365)
