"""AI 관리자 — 3dflowhub 를 매일 분석해 '근거 있는 개선 제안'을 올리고, 사람의 결정(수락·보류·거절·사유)에서 배운다.

흐름 (human-in-the-loop):
  1) review(): 사이트·수집·검색·독자 지표를 모아 LLM 에 보여주고 제안 최대 3개 + 사용자 의견에 대한 답변 + 한 줄 진단 생성
  2) 대시보드(자동화·진화 탭)에서 사람이 수락/보류/거절 + 사유 메모
  3) apply_accepted(): 수락된 제안 중 '안전한 자동 실행' 목록에 있는 것만 실제로 반영 (나머지는 '직접 작업 필요'로 남김)
  4) 다음 review() 때 과거 결정·사유·수락률을 다시 보여줘 취향을 학습

저장: memory/proposals.json — 이벤트 로그(추가만 함 → GitHub 병합 충돌 없음)
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import core

PROPOSALS_PATH = core.ROOT / "memory" / "proposals.json"
REVIEW_EVERY = timedelta(hours=24)
MAX_PROPOSALS = 3
CATEGORIES = ["콘텐츠", "수집", "사이트·UX", "검색(SEO)", "운영·비용", "수익", "현황판"]
FEED_REJECT_PATTERNS = ["키친", "주방", "인테리어", "요리", "레시피", "cooking", "kitchen", "recipe", "food"]
CONFIG_KEYS = {"interval": str, "max_items": int, "burst_items": int, "llm_daily_budget": int, "llm_fallback_daily": int, "buttondown_user": str}
STATUS_KO = {"new": "새 제안", "accepted": "수락", "held": "보류", "rejected": "거절", "done": "완료"}
PLAN_PATH = core.ROOT / "memory" / "plan.json"
GUIDES_MIN_SHARE = 0.6  # 남은 가이드 주제가 있는 동안 AI 몫의 최소 비율
DEFAULT_ALLOC = {"news": 0.2, "guides": 0.5, "roundups": 0.3}  # 에버그린(가이드·정리) 중심 — 요약 소식은 남들도 가진 정보
CALLS_PER_NEWS = 1.3   # 요약 1회 + 주제 밖·실패 여유
RESERVE = 6            # AI 관리자 분석·답변용으로 남겨 둠
SAFE_AUTO = ("keyword_hints", "editorial_note", "guide_topic", "add_feed")  # 자동 모드에서 스스로 수락해도 되는 행동


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events() -> list[dict]:
    return sorted([e for e in core._load_json(PROPOSALS_PATH, []) if isinstance(e, dict)], key=lambda e: e.get("at", ""))


def _append(*evs: dict) -> None:
    core._save_json(PROPOSALS_PATH, (core._load_json(PROPOSALS_PATH, []) + list(evs))[-3000:])


# ─────────────────────────── 상태 조회 ───────────────────────────
def board() -> dict:
    """이벤트 로그 → {'proposals': [...최신순], 'messages': [...], 'report': 마지막 진단}"""
    props: dict[str, dict] = {}
    msgs: dict[str, dict] = {}
    report: dict = {}
    for e in _events():
        k = e.get("kind")
        if k == "proposal":
            props[e["id"]] = {**e, "status": "new", "note": "", "applied": None}
        elif k == "decision" and e.get("id") in props:
            props[e["id"]].update(status=e.get("v", "new"), note=e.get("note", ""), decided_at=e["at"])
        elif k == "applied" and e.get("id") in props:
            props[e["id"]]["applied"] = e.get("result", "")
        elif k == "message":
            msgs[e["id"]] = {**e, "reply": None}
        elif k == "reply" and e.get("reply_to") in msgs:
            msgs[e["reply_to"]]["reply"] = e.get("text", "")
        elif k == "report":
            report = e
    return {"proposals": sorted(props.values(), key=lambda p: p["at"], reverse=True),
            "messages": sorted(msgs.values(), key=lambda m: m["at"], reverse=True), "report": report}


def manual_todo(site: str | None = None) -> list[dict]:
    """수락했지만 자동 실행 행동이 없어 사람(또는 Claude)이 직접 해야 하는 일 — 완료(done) 표시 전까지 남음."""
    return [p for p in board()["proposals"] if p["status"] == "accepted" and not (p.get("action") or {}).get("type")
            and (site is None or (p.get("site") or "3dflowhub") == site)]


def claude_request(p: dict) -> str:
    """Claude 에게 그대로 붙여넣을 작업 요청문."""
    import sites
    s = sites.SITES.get(p.get("site") or "3dflowhub", {})
    return (f"[{s.get('name', '')}] {p['title']}\n저장소: {s.get('repo', '')}\n근거: {p.get('evidence', '')}\n"
            f"할 일: {p.get('proposal', '')}" + (f"\n참고: {p['source']}" if p.get("source") else "")
            + ("\n규칙: " + s["rules"] if s.get("rules") else ""))


def similar_open(title: str, site: str) -> bool:
    """같은 사이트에 비슷한 제목의 제안이 열려 있거나 처리 대기 중이면 True (직원 간 중복 제안 방지)."""
    import re as _re
    words = set(_re.findall(r"[가-힣A-Za-z0-9]{2,}", title))
    for p in board()["proposals"]:
        if (p.get("site") or "3dflowhub") != site or p["status"] not in ("new", "held", "accepted"):
            continue
        other = set(_re.findall(r"[가-힣A-Za-z0-9]{2,}", p["title"]))
        if words and len(words & other) / max(1, min(len(words), len(other))) >= 0.6:
            return True
    return False


def acceptance_rate() -> float | None:
    decided = [p for p in board()["proposals"] if p["status"] in ("accepted", "rejected")]
    return round(sum(p["status"] == "accepted" for p in decided) / len(decided), 2) if decided else None


# ─────────────────────────── 사람의 결정 ───────────────────────────
def decide(pid: str, v: str, note: str = "") -> str:
    """수락/보류/거절 기록. 설정 변경류는 수락 즉시 이 PC 설정에 반영 (돌려줄 문구 반환)."""
    assert v in ("accepted", "held", "rejected", "new", "done")  # done = 직접 작업까지 끝남
    _append({"at": _now(), "kind": "decision", "id": pid, "v": v, "note": note.strip()[:500]})
    if v != "accepted":
        return ""
    p = next((x for x in board()["proposals"] if x["id"] == pid), None)
    act = (p or {}).get("action") or {}
    if act.get("type") in ("set_config", "glossary"):
        result = _apply(act)
        _append({"at": _now(), "kind": "applied", "id": pid, "result": result})
        return result
    return ""


def send_message(text: str) -> None:
    """사용자 → AI 관리자 의견/질문. 다음 분석 때 답변한다."""
    text = text.strip()[:1000]
    if text:
        _append({"at": _now(), "kind": "message", "id": "m-" + hashlib.md5(f"{_now()}{text}".encode()).hexdigest()[:10],
                 "text": text})


# ─────────────────────────── 실행 가능한 행동 ───────────────────────────
def describe(act: dict | None) -> str:
    """'수락하면 실제로 일어나는 일' (사람이 누르기 전에 보여줌)."""
    t = (act or {}).get("type")
    if t == "add_feed":
        return f"{act.get('domain')} 분야에 피드 추가: {act.get('url')} (다음 수집 때 실제로 글이 나오는지 검사 후 반영)"
    if t == "keyword_hints":
        return f"{act.get('domain')} 수집 키워드에 추가: {', '.join(act.get('keywords', [])[:6])}"
    if t == "editorial_note":
        return f"AI 요약 편집 지침에 추가: “{act.get('note', '')}”"
    if t == "set_config":
        return f"설정 변경: {act.get('key')} → {act.get('value')} (수락 즉시 적용)"
    if t == "glossary":
        return f"용어집 추가: {act.get('variants')} → {act.get('canon')} (수락 즉시 적용)"
    if t == "hire_role":
        r = act.get("role") or {}
        return (f"AI 직원 채용: {r.get('name')} — {r.get('every_hours')}시간마다, 하루 AI 최대 {r.get('daily_calls')}회 "
                f"(산출물: {', '.join(r.get('deliverables', []))}) · 언제든 현황판에서 쉬게 할 수 있음")
    if t == "pause_role":
        return f"AI 직원 쉬게 하기: {act.get('name') or act.get('id')} (다시 일하게 할 수 있음)"
    if t == "guide_topic":
        return f"기초 가이드 주제 추가: {act.get('tool')} · {act.get('title_ko')} (영상·단계별 사용법 페이지로 자동 생성)"
    return "자동 실행 없음 — 수락하면 코딩 에이전트가 다음 자동 실행(3시간마다)에 코드로 처리를 시도합니다 — 실패하면 '직접 작업 필요'에 남습니다"


def _valid_action(act) -> dict | None:
    if not isinstance(act, dict):
        return None
    t = act.get("type")
    if t == "add_feed" and act.get("domain") in core.DOMAINS and str(act.get("url", "")).startswith("http"):
        url_str = str(act["url"])[:300]
        if any(pat in url_str.lower() for pat in FEED_REJECT_PATTERNS):
            return None
        return {"type": t, "domain": act["domain"], "url": url_str}
    if t == "keyword_hints" and act.get("domain") in core.DOMAINS and isinstance(act.get("keywords"), list):
        return {"type": t, "domain": act["domain"], "keywords": [str(k)[:60] for k in act["keywords"][:6]]}
    if t == "editorial_note" and act.get("note"):
        return {"type": t, "note": str(act["note"])[:200]}
    if t == "set_config" and act.get("key") in CONFIG_KEYS:
        try:
            val = CONFIG_KEYS[act["key"]](act.get("value"))
        except (TypeError, ValueError):
            return None
        if act["key"] == "interval" and val not in core.INTERVALS:
            return None
        return {"type": t, "key": act["key"], "value": val}
    if t == "glossary" and act.get("canon") and act.get("variants"):
        return {"type": t, "canon": str(act["canon"])[:40], "variants": str(act["variants"])[:200]}
    if t == "hire_role":
        import staff
        role = staff.valid_role(act.get("role") or act)
        if role and role["id"] not in staff.roles():
            return {"type": t, "role": role}
        return None
    if t == "pause_role" and act.get("id"):
        import staff
        r = staff.roles().get(str(act["id"]))
        return {"type": t, "id": r["id"], "name": r["name"]} if r else None
    if t == "guide_topic" and act.get("tool") and act.get("name") and act.get("title_ko"):
        return {"type": t, "tool": str(act["tool"])[:30], "group": str(act.get("group") or "기능")[:20],
                "name": str(act["name"])[:60], "title_ko": str(act["title_ko"])[:60]}
    return None


def _apply(act: dict) -> str:
    t = act.get("type")
    if t == "set_config":
        core.save_config({act["key"]: act["value"]})
        return f"설정 {act['key']} = {act['value']} 적용"
    if t == "glossary":
        g = dict(core.load_config().get("glossary") or {})
        g[act["canon"]] = "|".join(x for x in [g.get(act["canon"], ""), act["variants"]] if x)
        core.save_config({"glossary": g})
        return f"용어집 {act['canon']} 추가"
    strategy = core.load_strategy()
    if t == "keyword_hints":
        hints = strategy.setdefault("keyword_hints", {})
        hints[act["domain"]] = list(dict.fromkeys(act["keywords"] + hints.get(act["domain"], [])))[:8]
    elif t == "editorial_note":
        import growth
        if growth.note_offtopic(act["note"]):
            return "사이트 주제 밖 지침 — 반영 안 함"
        growth.set_notes(strategy, strategy.get("prompt_notes", []) + [act["note"]], "관리자 제안 지침 추가")
    elif t == "hire_role":
        import staff
        return staff.hire(act["role"])
    elif t == "pause_role":
        import staff
        staff.set_status(act["id"], False)
        return f"{act.get('name')} 쉬게 함"
    elif t == "guide_topic":
        topics = strategy.setdefault("guide_topics", [])
        topic = [act["tool"], act["group"], act["name"], act["title_ko"], None]
        if topic not in topics:
            topics.append(topic)
    elif t == "add_feed":
        import evolve
        if not evolve.feed_ok(act["url"]):
            return "피드 검사 실패 (글이 3개 미만이거나 접속 불가) — 반영 안 함"
        extra = strategy.setdefault("extra_feeds", {})
        extra[act["domain"]] = list(dict.fromkeys(extra.get(act["domain"], []) + [act["url"]]))
    else:
        return ""
    core._save_json(core.STRATEGY_PATH, strategy)
    return "반영 완료"


def apply_accepted() -> list[str]:
    """수락됐지만 아직 반영 안 된 전략형 제안(피드·키워드·지침)을 반영 (GitHub 실행에서 호출)."""
    done = []
    for p in board()["proposals"]:
        act = p.get("action") or {}
        if (p.get("site") or "3dflowhub") != "3dflowhub":  # 다른 사이트 제안은 이 사이트 전략에 반영하지 않음
            continue
        if p["status"] == "accepted" and p["applied"] is None and act.get("type") in ("add_feed", "keyword_hints", "editorial_note", "guide_topic",
                                                                                "hire_role", "pause_role"):
            result = _apply(act)
            _append({"at": _now(), "kind": "applied", "id": p["id"], "result": result})
            done.append(f"{p['title']}: {result}")
    return done


# ─────────────────────────── 자동 모드: 오늘 배분 ───────────────────────────
def auto_mode() -> bool:
    return bool(core.load_config().get("auto_mode"))


def _day_start_utc() -> str:
    """Gemini 하루(태평양 자정) 시작 시각 (UTC ISO)."""
    from zoneinfo import ZoneInfo
    la = datetime.now(ZoneInfo("America/Los_Angeles")).replace(hour=0, minute=0, second=0, microsecond=0)
    return la.astimezone(timezone.utc).isoformat()


def _kst_day_start_utc() -> str:
    """한국 날짜 0시 (UTC ISO) — 현황판 '오늘' 표시용. AI 배분은 _day_start_utc(한도 기준 태평양 자정)를 씀."""
    from zoneinfo import ZoneInfo
    k = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=0, minute=0, second=0, microsecond=0)
    return k.astimezone(timezone.utc).isoformat()


def done_today(kst: bool = False) -> dict:
    """오늘 만든 것. kst=True 면 한국 날짜 기준(화면 표시), 기본은 AI 한도 하루 기준(배분 계산)."""
    start = _kst_day_start_utc() if kst else _day_start_utc()
    news = sum(1 for f in core.POSTS_DIR.glob("*.json") if (core._load_json(f, {}).get("collected_at") or "") >= start)
    try:
        import guides
        g = sum(1 for x in guides.load_all() if x.get("at", "") >= start)
    except Exception:
        g = 0
    r = sum(1 for f in core.ROUNDUP_DIR.glob("*.json") if core._load_json(f, {}).get("at", "") >= start) \
        if core.ROUNDUP_DIR.exists() else 0
    enriched = recipes_n = 0
    if kst:  # 화면 표시용 추가 지표 (배분 계산에는 쓰지 않음)
        for f in core.POSTS_DIR.glob("*.json"):
            e_at = core._load_json(f, {}).get("enriched_at") or ""
            enriched += e_at != "skip" and e_at >= start
        rdir = core.ROOT / "content" / "recipes"
        recipes_n = sum(1 for f in rdir.glob("*.json") if core._load_json(f, {}).get("at", "") >= start) if rdir.exists() else 0
        return {"news": news, "guides": g, "roundups": r, "enriched": enriched, "recipes": recipes_n}
    return {"news": news, "guides": g, "roundups": r}


def _roundup_candidates() -> int:
    try:
        import evolve
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        counts = Counter((p.get("domain"), p.get("category")) for p in
                         (core._load_json(f, {}) for f in core.POSTS_DIR.glob("*.json"))
                         if (p.get("collected_at") or "") >= cutoff and p.get("category")
                         and not str(p["category"]).startswith("기타"))
        fresh = (datetime.now(timezone.utc) - evolve.ROUNDUP_EVERY).isoformat()
        return sum(1 for (d, t), n in counts.items() if n >= evolve.ROUNDUP_MIN_POSTS
                   and core._load_json(evolve.roundup_path(d, t), {}).get("at", "") < fresh)
    except Exception:
        return 0


def _share(x: float) -> int:
    """기대값 x 를 정수로: 정수부 + 소수부 확률 (예: 0.4 → 40% 확률로 1개)."""
    import random
    return int(x) + (1 if random.random() < x - int(x) else 0)


def plan_today() -> dict:
    """오늘 남은 AI 여력을 뉴스 요약·기초 가이드·도구별 정리에 배분하고, 이번 실행 몫을 계산.
    비율은 AI 관리자의 하루 분석(allocation)을 따르고, 만들 거리가 없는 항목은 뉴스로 돌린다."""
    cfg = core.load_config()
    cap = core.llm_capacity_left()
    try:  # AI 직원들이 쓸 몫을 먼저 떼어 둠
        import staff
        team_calls = sum(r.get("daily_calls", 2) for r in staff.roles().values() if r["status"] == "active")
    except Exception:
        team_calls = 0
    usable = max(0, cap - RESERVE - team_calls)
    try:
        from zoneinfo import ZoneInfo
        la = datetime.now(ZoneInfo("America/Los_Angeles"))
        hours_left = 24 - la.hour - la.minute / 60
    except Exception:
        hours_left = 12
    interval = core.INTERVALS.get(cfg.get("interval"), 3600) or 600
    runs_left = max(1, int(hours_left * 3600 // interval))
    rep = board()["report"]
    alloc = dict(rep.get("allocation") or DEFAULT_ALLOC)
    news_cap = float(cfg.get("alloc_news_cap", 0.3))  # 뉴스 상한: 차별성 낮은 요약 소식이 배분을 다 먹지 않도록
    if alloc.get("news", 0) > news_cap:
        spare = alloc["news"] - news_cap
        alloc["news"] = news_cap
        alloc["guides"] = alloc.get("guides", 0) + spare * 0.6
        alloc["roundups"] = alloc.get("roundups", 0) + spare * 0.4
    try:
        import guides
        pending_guides = len(guides.pending())
    except Exception:
        pending_guides = 0
    cand = _roundup_candidates()
    # 만들 거리가 없는 항목의 몫은 다른 에버그린(가이드↔정리)으로 먼저, 둘 다 없을 때만 뉴스로
    if not cand:
        to = "guides" if pending_guides else "news"
        alloc[to] = alloc.get(to, 0) + alloc.pop("roundups", 0)
        alloc["roundups"] = 0
    if not pending_guides:
        to = "roundups" if cand else "news"
        alloc[to] = alloc.get(to, 0) + alloc.pop("guides", 0)
        alloc["guides"] = 0
    tot = sum(alloc.values()) or 1
    alloc = {k: round(v / tot, 2) for k, v in alloc.items()}
    floor = float(cfg.get("alloc_guides_min", GUIDES_MIN_SHARE))
    if pending_guides and alloc.get("guides", 0) < floor:  # 기초 가이드 우선 (운영자 요청 — 도구마다 100개 이상)
        rest = sum(v for k, v in alloc.items() if k != "guides") or 1
        alloc = {k: (floor if k == "guides" else round(v / rest * (1 - floor), 2)) for k, v in alloc.items()}
    per_run_calls = usable / runs_left
    plan = {
        "day": core.llm_day(), "at": _now(), "capacity_left": cap, "runs_left": runs_left,
        "alloc": alloc, "reason": rep.get("allocation_reason") or ("AI 관리자 분석 비율" if rep.get("allocation")
                                                                 else "기본 배분 (AI 관리자 분석 전)"),
        "news_per_run": max(1, min(15, round(per_run_calls * alloc["news"] / CALLS_PER_NEWS))) if usable else 0,
        "guides_now": min(3, pending_guides, _share(per_run_calls * alloc["guides"])) if usable else 0,
        "roundups_now": min(3, cand, _share(per_run_calls * alloc["roundups"])) if usable else 0,
        "today_target": {k: int(usable * v / (CALLS_PER_NEWS if k == "news" else 1)) for k, v in alloc.items()},
        "done": done_today(), "pending_guides": pending_guides, "roundup_candidates": cand,
    }
    core._save_json(PLAN_PATH, plan)
    return plan


def _auto_accept(new_ids: list[str]) -> list[str]:
    """자동 모드: 위험도 '낮음'(키워드·가이드 주제)만 스스로 수락. 지침·피드·설정 변경은 사람에게 남김."""
    import growth
    done = []
    for p in board()["proposals"]:
        act = p.get("action") or {}
        if p["id"] in new_ids and p["status"] == "new" and act.get("type") in SAFE_AUTO                 and growth.risk_of(act) == "low":  # 위험도 '낮음'만 자동 수락, 나머지는 사람 승인
            _append({"at": _now(), "kind": "decision", "id": p["id"], "v": "accepted", "note": "자동 모드: 자동 수락",
                     "auto": True})
            done.append(p["title"])
    return done


# ─────────────────────────── 분석 ───────────────────────────
def _dashboard_info() -> dict:
    """'큐레이션 현황판'(운영자용 Streamlit 앱, app.py) — AI 관리자의 관리 대상. 사이트(독자용)와 다름."""
    b = board()
    props = b["proposals"]
    return {
        "what": "운영자(사장님)가 결정·확인하는 Streamlit 앱. 로컬 + https://3dflowmanager.streamlit.app (비공개). "
                "독자는 보지 않는다. 사이트 홈에 통계를 올리는 것은 현황판 개선이 아님.",
        "tabs": ["🏠 오늘(결정할 일·홍보 대기함·무엇이 읽히나)", "📊 개요·수익(수집·방문 추이, 수익·방문)", "📰 글 목록(추천·숨김·가이드 검토·실무 팁)",
                 "🧬 자동화·진화(AI 관리자·AI 팀·교본)", "📝 티스토리", "🛠 설정",
                 "사이트 전환: 🏢 전체 요약 / 🧊 3dflowhub / 💰 life-after-60"],
        "owner_load": {"waiting_decisions": sum(p["status"] == "new" for p in props),
                       "manual_todo": len(manual_todo()), "held": sum(p["status"] == "held" for p in props)},
        "how_to_improve": "category '현황판' 으로 제안 (action 없음 → 직접 작업 목록 → Claude 가 app.py 수정). "
                          "예: 결정 대기가 쌓이면 한 번에 처리하는 방법, 휴대폰에서 보기 쉬운 배치, 자주 쓰는 것을 위로.",
    }


def _team_stats() -> list[dict]:
    """AI 직원별 현황 (채용·휴식 판단 근거): 산출물 수와 사람의 반응."""
    try:
        import staff
        box = staff.outbox()
        out = []
        for r in staff.roles().values():
            mine = [x for x in box if x.get("role") == r["id"]]
            out.append({"id": r["id"], "name": r["name"], "status": r["status"], "mission": r["mission"][:120],
                        "promos": len(mine), "posted": sum(x["status"] == "posted" for x in mine),
                        "skipped": sum(x["status"] == "skipped" for x in mine),
                        "waiting": sum(x["status"] == "new" for x in mine), "last_note": r.get("last_summary", "")})
        return out
    except Exception:
        return []


def _guide_stats() -> dict:
    try:
        import guides
        made = guides.load_all()
        queued = len(guides.pending())
        out = {"published": len(made), "queued_topics": queued, "by_tool": Counter(g["tool"] for g in made)}
        if queued < 10:  # 만들 거리가 떨어지면 남는 AI 여력이 놀게 됨 → 주제 보충 요청
            out["note"] = (f"Only {queued} guide topics queued; spare AI capacity will go unused. Propose up to 3 "
                           "guide_topic actions for popular tools/features not yet covered.")
        return out
    except Exception:
        return {}


def snapshot() -> dict:
    """AI 관리자가 볼 지표 (숫자 근거)."""
    posts = [core._load_json(f, {}) for f in core.POSTS_DIR.glob("*.json")]
    posts = [p for p in posts if p.get("title_ko")]
    now = datetime.now(timezone.utc)
    recent = [p for p in posts if (p.get("collected_at") or "") >= (now - timedelta(days=7)).isoformat()]
    runs = core.load_memory().get("runs", [])[-60:]
    errs = Counter(e.split(":")[0][:40] for r in runs for e in r.get("errors", []))
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {}).get("pages") or {}
    cur = core.curation_state()
    strategy = core.load_strategy()
    try:
        import gsc
        search = {"top": gsc.top_queries(10), "opportunities": [r["key"] for r in gsc.opportunities(5)]}
    except Exception:
        search = {}
    return {
        "posts_total": len(posts), "posts_last_7d": len(recent),
        "by_domain_7d": Counter(p.get("domain") for p in recent),
        "by_tool_7d": Counter(f"{p.get('domain')}/{p.get('category')}" for p in recent).most_common(12),
        "by_topic_7d": Counter(p.get("topic") for p in recent),
        "posts_without_image_pct": round(100 * sum(not (p.get("media") or {}).get("image") for p in recent) / max(1, len(recent))),
        "runs_recent": len(runs), "collected": sum(r.get("collected", 0) for r in runs),
        "saved": sum(r.get("saved", 0) for r in runs), "error_counts": errs.most_common(8),
        "ai_usage_today": core.llm_usage_today(), "ai_budget": core.load_config().get("llm_daily_budget"),
        "ai_fallback_today": core.llm_fallback_usage(), "ai_real_limit_learned": core.llm_quota_status()["learned_limit"],
        "ai_note": "llm_daily_budget is only a self-imposed cap; Gemini's free quota (~280 calls/day observed) is the "
                   "real ceiling, so raising the budget adds no capacity. Extra capacity comes from fallback "
                   "providers (Groq etc.) or fewer wasted calls.",
        "site_views_30d": perf.get("pv_30d"), "top_referrers": perf.get("refs"),
        "editor_picks": sum(v == "pick" for v in cur.values()), "editor_hidden": sum(v == "hide" for v in cur.values()),
        "reader_interest": strategy.get("tool_interest", {}), "search_console": search,
        "roundup_pages": len(list(core.ROUNDUP_DIR.glob("*.json"))) if core.ROUNDUP_DIR.exists() else 0,
        "views_30d_by_content_type": perf.get("by_kind"),  # 뉴스·기초 가이드·도구별 정리 중 무엇이 읽히나 → 배분 근거
        # 자동 모드 상태: 이미 하고 있는 일(배분·가이드 우선)을 다시 제안하지 않도록
        "auto_mode": {"on": bool(core.load_config().get("auto_mode")),
                      "note": "When on, today's AI capacity is already split automatically between news, guides and "
                              "roundups using your 'allocation' output, and safe proposals are auto-accepted. To shift "
                              "priorities, change 'allocation' instead of proposing interval/budget changes.",
                      "today_plan": {k: core._load_json(PLAN_PATH, {}).get(k) for k in ("alloc", "done", "capacity_left")},
                      "fallback_ai": [f["name"] for f in core.fallback_providers()]},
        "allowed_intervals": list(core.INTERVALS),
        "team": _team_stats(),
        "dashboard": _dashboard_info(),
        "staff_capabilities": {"promo": "채널별 홍보 글 초안", "proposal": "개선 제안", "note": "업무 일지",
                               "image": "브랜드 템플릿 홍보 이미지(square/x/story) — 디자이너 직무에 적합, 사이트 디자인 정보도 받음"},
        "basics_guides": _guide_stats(),
        "config": {k: core.load_config().get(k) for k in ("interval", "max_items", "domains")},
    }


def review(force: bool = False) -> dict | None:
    """하루 1회(또는 사용자 의견이 오면) 분석 → 제안·답변·진단 저장. AI 호출 1회."""
    b = board()
    last = b["report"].get("at", "")
    pending_msgs = [m for m in b["messages"] if m["reply"] is None]
    due = not last or last < (datetime.now(timezone.utc) - REVIEW_EVERY).isoformat()
    if not (force or due or pending_msgs) or core.llm_budget_left() < 10:
        return None
    open_titles = [p["title"] for p in b["proposals"] if p["status"] in ("new", "held")]
    history = [{"title": p["title"], "category": p.get("category"), "decision": STATUS_KO[p["status"]],
                "reason": p.get("note", ""), "applied": p.get("applied")}
               for p in b["proposals"] if p["status"] != "new"][:20]
    prompt = (
        "You are the AI site manager of 3dflowhub (https://heo-j-h.github.io/3dflowhub/), an automated Korean "
        f"curation site about {core.domain_topics()}. Mission: keep evolving the site — analyze metrics, find "
        "weaknesses, and propose concrete improvements to the human owner, who decides.\n"
        f"Metrics (last ~7 days / recent runs): {json.dumps(snapshot(), ensure_ascii=False, default=str)[:5000]}\n"
        f"Owner's past decisions on your proposals (learn their preferences; do not repeat rejected ideas unless "
        f"the reason is addressed): {json.dumps(history, ensure_ascii=False)[:2500]}\n"
        f"Acceptance rate so far: {acceptance_rate()}\n"
        f"Proposals still open (do not duplicate): {json.dumps(open_titles, ensure_ascii=False)}\n"
        f"Owner's messages to answer: {json.dumps([{'id': m['id'], 'text': m['text']} for m in pending_msgs], ensure_ascii=False)}\n"
        "Return JSON in Korean:\n"
        ' "summary": 2-3 sentences: overall health of the site today, citing numbers,\n'
        f' "proposals": up to {MAX_PROPOSALS} items, most impactful first, each {{"title": <=40 chars, '
        f'"category": one of {CATEGORIES}, "evidence": the specific numbers that show the problem, written as plain '
        'Korean sentences (never raw field names like site_views_30d), '
        '"proposal": what to change and how, "expected": expected effect, "effort": "낮음"|"보통"|"높음", '
        '"action": optional machine action or null — one of '
        '{"type":"add_feed","domain":D,"url":real RSS URL} | {"type":"keyword_hints","domain":D,"keywords":[...English search terms]} | '
        '{"type":"editorial_note","note":Korean rule for article writing} | '
        f'{{"type":"set_config","key":one of {list(CONFIG_KEYS)},"value":...}} | '
        '{"type":"glossary","canon":official name,"variants":"wrong spelling 1|wrong spelling 2"} | '
        '{"type":"guide_topic","tool":e.g. "3ds Max","group":e.g. "모디파이어","name":English feature name,'
        '"title_ko":Korean page title} (evergreen basics reference page with video) | '
        '{"type":"hire_role","role":{"name":"emoji + Korean job title","mission":"what this staff member does every '
        'cycle, concretely","deliverables":["promo"|"proposal"|"note"|"image"],"every_hours":6-168,"daily_calls":1-3,'
        '"playbook":"5-10 Korean bullet lines: how to do this job well — methods, quality bar, what to avoid"}} — '
        'propose hiring ONLY when there is recurring work no current team member covers (see metrics.team), like a '
        'company hiring | {"type":"pause_role","id":team member id} — when a member\'s output is mostly skipped or no '
        'longer needed}},\n'
        ' "replies": [{"id": message id, "text": helpful Korean answer}] for each owner message,\n'
        ' "allocation": how to split today\'s remaining AI calls between content types, as fractions summing to 1: '
        '{"news": new article summaries, "guides": evergreen basics guides with video, "roundups": monthly tool '
        'roundups}, plus "allocation_reason": one Korean sentence why (based on views, gaps, search demand).\n'
        f"Domains D: {list(core.DOMAINS)}. Only propose things supported by the metrics; be specific, not generic."
    )
    out = core._parse_json(core.llm(prompt, system="You are the AI site manager (team lead) of 3dflowhub." + core.playbook("common", "manager"),
                                     max_tokens=2000, json_mode=True))
    if not isinstance(out, dict):
        return None
    now = _now()
    alloc = out.get("allocation") if isinstance(out.get("allocation"), dict) else {}
    try:
        alloc = {k: max(0.0, float(alloc.get(k, 0))) for k in DEFAULT_ALLOC}
        alloc = {k: round(v / sum(alloc.values()), 2) for k, v in alloc.items()} if sum(alloc.values()) else {}
    except (TypeError, ValueError):
        alloc = {}
    evs = [{"at": now, "kind": "report", "id": "r-" + now[:16], "text": core.fix_terms(str(out.get("summary", "")))[:800],
            "allocation": alloc or None, "allocation_reason": str(out.get("allocation_reason", ""))[:300]}]
    for p in (out.get("proposals") or [])[:MAX_PROPOSALS]:
        if not isinstance(p, dict) or not p.get("title") or p["title"] in open_titles:
            continue
        pid = "p-" + hashlib.md5(f"{now}{p['title']}".encode()).hexdigest()[:10]
        evs.append({"at": now, "kind": "proposal", "id": pid, "title": str(p["title"])[:80],
                    "category": p.get("category") if p.get("category") in CATEGORIES else "운영·비용",
                    "evidence": core.fix_terms(str(p.get("evidence", "")))[:600],
                    "proposal": core.fix_terms(str(p.get("proposal", "")))[:900],
                    "expected": str(p.get("expected", ""))[:300],
                    "effort": p.get("effort") if p.get("effort") in ("낮음", "보통", "높음") else "보통",
                    "action": _valid_action(p.get("action"))})
        import growth
        evs[-1]["risk"] = growth.risk_of(evs[-1]["action"])  # 낮음=자동 수락 가능, 중간·높음=사람 승인
    ids = {m["id"] for m in pending_msgs}
    for r in out.get("replies") or []:
        if isinstance(r, dict) and r.get("id") in ids and r.get("text"):
            evs.append({"at": now, "kind": "reply", "id": "y-" + r["id"], "reply_to": r["id"], "text": str(r["text"])[:1500]})
    _append(*evs)
    if auto_mode():  # 자동 모드: 안전한 제안은 스스로 수락 → 바로 다음 실행에서 반영
        accepted = _auto_accept([e["id"] for e in evs if e["kind"] == "proposal"])
        if accepted:
            core.log.info("AI 관리자 자동 수락: %s", accepted)
            apply_accepted()
    core.log.info("AI 관리자: 제안 %d개, 답변 %d개", sum(e["kind"] == "proposal" for e in evs),
                  sum(e["kind"] == "reply" for e in evs))
    return out
