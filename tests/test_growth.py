import core
import growth


def test_clean_notes_drops_offtopic_and_duplicates():
    notes = ["제목에 도구명을 앞에 배치한다", "반영 검토: 군 복무 국민연금 가입기간 인정",
             "제목에 도구명을 앞에 배치한다.", "본문 1,500자 이상"]
    out = growth.clean_notes(notes)
    assert out == ["제목에 도구명을 앞에 배치한다.", "본문 1,500자 이상"]


def test_clean_notes_caps_count_keeping_latest():
    notes = [f"규칙 {c} 번째 지침 {c}" for c in "가나다라마바사아"]
    out = growth.clean_notes(notes)
    assert len(out) == growth.CORE_RULES["max_notes"] and out[-1] == notes[-1]


def test_set_notes_snapshots_previous():
    s = {"prompt_notes": ["기존 지침"]}
    assert growth.set_notes(s, ["새 지침"], "테스트")
    assert s["prompt_notes"] == ["새 지침"] and s["snapshots"][-1]["notes"] == ["기존 지침"]
    assert s["notes_updated_at"]


def test_rollback_when_current_clearly_worse():
    good, bad = ["좋은 지침"], ["나쁜 지침"]
    gv, bv = core.strategy_version(good), core.strategy_version(bad)
    s = {"prompt_notes": bad, "note_versions": {gv: good, bv: bad}}
    traj = [{"ver": bv, "runs": 5, "score": 0.2}, {"ver": gv, "runs": 5, "score": 0.6}]
    assert growth.rollback_if_worse(s, traj)
    assert s["prompt_notes"] == good


def test_no_rollback_when_close():
    a, b = ["지침 에이"], ["지침 비"]
    s = {"prompt_notes": a, "note_versions": {core.strategy_version(a): a, core.strategy_version(b): b}}
    traj = [{"ver": core.strategy_version(a), "runs": 5, "score": 0.55},
            {"ver": core.strategy_version(b), "runs": 5, "score": 0.6}]
    assert growth.rollback_if_worse(s, traj) == ""


def test_risk_levels():
    assert growth.risk_of({"type": "keyword_hints"}) == "low"
    assert growth.risk_of({"type": "editorial_note"}) == "medium"
    assert growth.risk_of({"type": "set_config"}) == "high"
    assert growth.risk_of(None) == "high"


def test_merge_strategy_takes_newer_notes_not_union():
    remote = {"prompt_notes": ["옛 지침"], "notes_updated_at": "2026-10-01"}
    local = {"prompt_notes": ["새 지침"], "notes_updated_at": "2026-10-02"}
    assert core.merge_memory("memory/strategy.json", remote, local)["prompt_notes"] == ["새 지침"]


def test_underperformers():
    perf = {"by_group": {"A/x": {"posts": 10, "views": 2, "avg": 0.2},
                         "A/y": {"posts": 10, "views": 200, "avg": 20.0}}}
    assert growth.underperformers(perf) == ["A/x"]


def test_capacity_keeps_fallback_reserve(monkeypatch):
    monkeypatch.setattr(core, "fallback_providers", lambda: [{"left": 300}])
    monkeypatch.setattr(core, "llm_quota_status", lambda: {"exhausted": True})
    assert core.llm_capacity_left() == 300 - core.FALLBACK_RESERVE


def test_fallback_minute_limit_not_daily(monkeypatch):
    class R:
        status_code = 429
        headers = {"retry-after": "0"}
        text = "Rate limit reached for model on tokens per minute (TPM): Limit 6000"
        ok = False
    monkeypatch.setattr(core.requests, "post", lambda *a, **k: R())
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(RuntimeError) as e:
        core._llm_call("u", "k", "m", "p", "s", 10, False)
    assert not isinstance(e.value, core.LLMBudgetExceeded)  # 분당 제한은 '오늘 소진'이 아님
    R.text = "Rate limit reached on requests per day (RPD): Limit 1000"
    with pytest.raises(core.LLMBudgetExceeded):
        core._llm_call("u", "k", "m", "p", "s", 10, False)


def test_guide_quality_and_daily_cap(monkeypatch, tmp_path):
    import guides
    assert not guides.passes_quality({"steps": ["a"] * 4, "params": [{}], "grounded": True})
    assert guides.passes_quality({"steps": ["a"] * 4, "params": [{}, {}], "videos": [1]})
    monkeypatch.setattr(guides, "GUIDE_DIR", tmp_path)
    monkeypatch.setattr(guides, "load_all", lambda: [{"at": guides.datetime.now(guides.timezone.utc).isoformat()}] * 10)
    monkeypatch.setattr(core, "llm_budget_left", lambda: 999)
    called = []
    monkeypatch.setattr(guides, "make_guide", lambda *a: called.append(a))
    assert guides.write_guides(5) == [] and not called  # 오늘 이미 10개 → 더 안 만듦


def test_iso_tz():
    import build_site
    assert build_site.iso_tz("2026-10-26T14:22:52") == "2026-10-26T14:22:52+00:00"
    assert build_site.iso_tz("2026-10-26T14:22:52.123+09:00") == "2026-10-26T14:22:52+09:00"


def test_promo_body_gets_link():
    import staff
    u = "https://heo-j-h.github.io/life-after-60/?utm_source=kakao"
    assert staff.with_link("소개합니다.\n\n👉 시뮬레이터 해보기:", u).endswith("해보기: " + u)
    assert staff.with_link("소개합니다.", u).endswith("👉 " + u)
    assert staff.with_link("링크 " + u, u).count(u) == 1
