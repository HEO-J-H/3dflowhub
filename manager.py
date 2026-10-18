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
CATEGORIES = ["콘텐츠", "수집", "사이트·UX", "검색(SEO)", "운영·비용", "수익"]
CONFIG_KEYS = {"interval": str, "max_items": int, "burst_items": int, "llm_daily_budget": int, "llm_fallback_daily": int}
STATUS_KO = {"new": "새 제안", "accepted": "수락", "held": "보류", "rejected": "거절"}


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


def acceptance_rate() -> float | None:
    decided = [p for p in board()["proposals"] if p["status"] in ("accepted", "rejected")]
    return round(sum(p["status"] == "accepted" for p in decided) / len(decided), 2) if decided else None


# ─────────────────────────── 사람의 결정 ───────────────────────────
def decide(pid: str, v: str, note: str = "") -> str:
    """수락/보류/거절 기록. 설정 변경류는 수락 즉시 이 PC 설정에 반영 (돌려줄 문구 반환)."""
    assert v in ("accepted", "held", "rejected", "new")
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
    return "자동 실행 없음 — 수락하면 '직접 작업 필요' 목록에 남습니다 (Claude 에게 이 제안을 그대로 요청하면 됩니다)"


def _valid_action(act) -> dict | None:
    if not isinstance(act, dict):
        return None
    t = act.get("type")
    if t == "add_feed" and act.get("domain") in core.DOMAINS and str(act.get("url", "")).startswith("http"):
        return {"type": t, "domain": act["domain"], "url": str(act["url"])[:300]}
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
        strategy["prompt_notes"] = (strategy.get("prompt_notes", []) + [act["note"]])[-6:]
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
        if p["status"] == "accepted" and p["applied"] is None and act.get("type") in ("add_feed", "keyword_hints", "editorial_note"):
            result = _apply(act)
            _append({"at": _now(), "kind": "applied", "id": p["id"], "result": result})
            done.append(f"{p['title']}: {result}")
    return done


# ─────────────────────────── 분석 ───────────────────────────
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
        '{"type":"glossary","canon":official name,"variants":"wrong spelling 1|wrong spelling 2"}},\n'
        ' "replies": [{"id": message id, "text": helpful Korean answer}] for each owner message.\n'
        f"Domains D: {list(core.DOMAINS)}. Only propose things supported by the metrics; be specific, not generic."
    )
    out = core._parse_json(core.llm(prompt, system="You are a pragmatic product manager and SEO/content strategist.",
                                     max_tokens=2000, json_mode=True))
    if not isinstance(out, dict):
        return None
    now = _now()
    evs = [{"at": now, "kind": "report", "id": "r-" + now[:16], "text": core.fix_terms(str(out.get("summary", "")))[:800]}]
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
    ids = {m["id"] for m in pending_msgs}
    for r in out.get("replies") or []:
        if isinstance(r, dict) and r.get("id") in ids and r.get("text"):
            evs.append({"at": now, "kind": "reply", "id": "y-" + r["id"], "reply_to": r["id"], "text": str(r["text"])[:1500]})
    _append(*evs)
    core.log.info("AI 관리자: 제안 %d개, 답변 %d개", sum(e["kind"] == "proposal" for e in evs),
                  sum(e["kind"] == "reply" for e in evs))
    return out
