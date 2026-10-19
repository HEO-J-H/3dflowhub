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
