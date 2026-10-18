"""AI 팀(직원) — AI 관리자가 업무에 따라 '채용'하는 역할들. 사람의 승인으로 채용되고, 정해진 주기마다 일한다.

설계 (Aime 의 Actor Factory 처럼 필요한 역할을 그때그때 만들되, 채용은 사람 승인):
  - 역할 = {이름, 임무, 산출물 종류, 주기, 하루 AI 사용 한도} → memory/roles.json (이벤트 로그: 추가만 함)
  - 산출물: promo(홍보 글 초안 → 현황판 '홍보 대기함', 사람이 복사·게시)
            proposal(개선 제안 → AI 관리자 제안 보드, 사람이 수락·거절)
            note(업무 일지 → 다음 실행과 AI 관리자가 참고)
  - 사람의 반응(게시함/건너뜀, 제안 수락/거절 사유)을 다음 업무 때 보여줘 스스로 배운다
  - 기본 직원: 📣 마케터 (홍보 글·검색 기회·주간 뉴스레터)
홍보는 '자동 게시하지 않음' — 커뮤니티 자동 게시는 스팸 차단·약관 위반 위험이 커서 사람이 올린다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import core

ROLES_PATH = core.ROOT / "memory" / "roles.json"     # 역할 이벤트: hire / pause / resume / run
OUTBOX_PATH = core.ROOT / "memory" / "outbox.json"   # 홍보 대기함 이벤트: item / status
SITE = "https://heo-j-h.github.io/3dflowhub/"
DELIVERABLES = ("promo", "proposal", "note", "image")
DEFAULT_CHANNELS = ["네이버 카페 (3D 커뮤니티)", "X (트위터)", "인스타그램 캡션", "디스코드"]

MARKETER = {
    "id": "marketer", "name": "📣 마케터",
    "mission": ("3dflowhub 를 3D 아티스트·학생·게임/VFX 실무자에게 알려 방문을 늘린다. "
                "① 채널별 홍보 글 초안(기초 가이드·도구별 정리·주목할 소식 위주, 채널 말투·길이에 맞춤, 광고 티 최소화) "
                "② 검색 기회: 노출은 많은데 클릭이 적은 검색어 → 제목·설명 개선 제안, 사람들이 찾는데 없는 주제 → 기초 가이드 주제 제안 "
                "③ 주 1회 뉴스레터 초안(이번 주 요약 기반)"),
    "deliverables": ["promo", "proposal"], "every_hours": 24, "daily_calls": 4,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events(path) -> list[dict]:
    return sorted([e for e in core._load_json(path, []) if isinstance(e, dict)], key=lambda e: e.get("at", ""))


def _append(path, *evs: dict) -> None:
    core._save_json(path, (core._load_json(path, []) + list(evs))[-3000:])


# ─────────────────────────── 역할(직원) ───────────────────────────
def roles() -> dict[str, dict]:
    """현재 역할 목록 {id: role + status, last_run}. 마케터는 기본 채용."""
    out: dict[str, dict] = {"marketer": {**MARKETER, "status": "active", "hired_at": "", "hired_by": "기본",
                                         "last_run": ""}}
    for e in _events(ROLES_PATH):
        rid = e.get("id")
        if e.get("kind") == "hire" and rid:
            out[rid] = {**(e.get("role") or {}), "id": rid, "status": "active", "hired_at": e["at"],
                        "hired_by": e.get("by", "AI 관리자"), "last_run": out.get(rid, {}).get("last_run", "")}
        elif e.get("kind") in ("pause", "resume") and rid in out:
            out[rid]["status"] = "paused" if e["kind"] == "pause" else "active"
        elif e.get("kind") == "run" and rid in out:
            out[rid]["last_run"] = e["at"]
            out[rid]["last_summary"] = e.get("summary", "")
    return out


def valid_role(r) -> dict | None:
    """AI 관리자가 제안한 채용안 검증 (산출물 종류·주기·하루 사용량 제한)."""
    if not isinstance(r, dict) or not r.get("name") or not r.get("mission"):
        return None
    deliv = [d for d in (r.get("deliverables") or [r.get("deliverable")]) if d in DELIVERABLES] or ["proposal"]
    try:
        every = min(168, max(6, int(r.get("every_hours", 24))))
        calls = min(6, max(1, int(r.get("daily_calls", 2))))
    except (TypeError, ValueError):
        return None
    rid = "r-" + hashlib.md5(str(r["name"]).encode()).hexdigest()[:8]
    return {"id": rid, "name": str(r["name"])[:30], "mission": str(r["mission"])[:600],
            "deliverables": deliv, "every_hours": every, "daily_calls": calls,
            "playbook": str(r.get("playbook") or "")[:1500]}  # 채용 때 팀장이 써 주는 직무 교본


def hire(role: dict, by: str = "AI 관리자 제안 · 사람 승인") -> str:
    _append(ROLES_PATH, {"at": _now(), "kind": "hire", "id": role["id"], "role": role, "by": by})
    return f"{role['name']} 채용 — {role['every_hours']}시간마다, 하루 AI {role['daily_calls']}회"


def set_status(rid: str, active: bool) -> None:
    _append(ROLES_PATH, {"at": _now(), "kind": "resume" if active else "pause", "id": rid})


# ─────────────────────────── 홍보 대기함 ───────────────────────────
def outbox() -> list[dict]:
    items: dict[str, dict] = {}
    for e in _events(OUTBOX_PATH):
        if e.get("kind") == "item":
            items[e["id"]] = {**e, "status": "new"}
        elif e.get("kind") == "status" and e.get("id") in items:
            items[e["id"]].update(status=e.get("v", "new"), note=e.get("note", ""))
    return sorted(items.values(), key=lambda x: x["at"], reverse=True)


def set_outbox(item_id: str, v: str, note: str = "") -> None:
    """v: posted(게시함) / skipped(건너뜀) / new"""
    _append(OUTBOX_PATH, {"at": _now(), "kind": "status", "id": item_id, "v": v, "note": note[:200]})


def tracked(url: str, channel: str, role_id: str) -> str:
    """홍보 링크에 출처 표시 (GoatCounter 가 utm_source/utm_campaign 을 자동 인식 → 채널별 방문 집계)."""
    if not url.startswith(SITE):
        return url
    src = {"네이버": "naver_cafe", "X": "x", "인스타": "instagram", "디스코드": "discord", "뉴스레터": "newsletter"}
    s = next((v for k, v in src.items() if k in channel), "promo")
    return url + ("&" if "?" in url else "?") + urlencode({"utm_source": s, "utm_campaign": role_id})


# ─────────────────────────── 업무 수행 ───────────────────────────
def _context(role: dict) -> dict:
    """역할이 일할 때 보는 자료: 사이트 지표 + 최근 콘텐츠 + 사람의 반응."""
    import manager
    try:
        import guides
        gl = [{"title": g["title"], "tool": g["tool"], "url": f"{SITE}learn/{g['id']}/", "video": bool(g.get("videos"))}
              for g in guides.load_all()][-15:]
    except Exception:
        gl = []
    posts = sorted((core._load_json(f, {}) | {"id": f.stem} for f in core.POSTS_DIR.glob("*.json")),
                   key=lambda p: p.get("collected_at") or "", reverse=True)
    recent = [{"title": p.get("title_ko"), "tool": p.get("category"), "url": f"{SITE}p/{p['id']}.html"}
              for p in posts[:12] if p.get("title_ko")]
    mine = [x for x in outbox() if x.get("role") == role["id"]][:12]
    feedback = [{"channel": x.get("channel"), "title": x.get("title"), "result": x["status"], "note": x.get("note", "")}
                for x in mine if x["status"] != "new"]
    return {"site_metrics": manager.snapshot(), "basics_guides": gl, "recent_news": recent,
            "channels": core.load_config().get("promo_channels") or DEFAULT_CHANNELS,
            "your_past_output_feedback": feedback,
            "waiting_to_post": [{"channel": x.get("channel"), "page": x.get("url", "").split("?")[0]}
                                for x in mine if x["status"] == "new"],
            "recently_posted": [{"channel": x.get("channel"), "page": x.get("url", "").split("?")[0]}
                                for x in mine if x["status"] == "posted"][:10],
            "weekly_page": f"{SITE}weekly/",
            **({"site_design": _design_snapshot()} if _is_designer(role) else {})}


def _is_designer(role: dict) -> bool:
    return "image" in (role.get("deliverables") or []) or "디자인" in role.get("mission", "") \
        or "디자이너" in role.get("name", "")


def _design_snapshot() -> dict:
    try:
        import design
        return design.site_snapshot()
    except Exception as e:
        return {"error": str(e)[:100]}


def run_role(role: dict) -> dict:
    """역할 한 번 수행: 산출물 생성 → 홍보 대기함 / 제안 보드 / 업무 일지."""
    import manager
    ctx = _context(role)
    want = role.get("deliverables") or ["proposal"]
    prompt = (
        f"You are '{role['name']}', a staff member of the 3dflowhub site team (Korean 3D/game/VFX/AI-3D curation site, "
        f"{SITE}). Your mission: {role['mission']}\n"
        f"Context (metrics, content, how the owner reacted to your past work — learn from it): "
        f"{json.dumps(ctx, ensure_ascii=False, default=str)[:7000]}\n"
        "Rules: write in natural Korean; use only real URLs from the context; no false claims or fake numbers; "
        "promotional posts must be useful first (share what readers learn), not spammy; respect each channel's style "
        "and length (X: ≤240 chars, Naver cafe: title + 3-6 lines, Instagram: caption + 5-8 hashtags, Discord: short "
        "friendly message). If waiting_to_post is long, make fewer new ones; never promote a page that is already in "
        "waiting_to_post or recently_posted for the same channel. Hashtags have no spaces (#3dsMax, not #3ds Max).\n"
        f"Return JSON with keys you are allowed to produce ({want}):\n"
        ' "promo": up to 4 [{"channel": one of the channels or "뉴스레터", "title": short, "body": ready-to-paste text, '
        '"url": the page to link}],\n'
        ' "proposal": up to 2 [{"title": <=40 chars, "category": one of ' + json.dumps(manager.CATEGORIES, ensure_ascii=False)
        + ', "evidence": numbers in plain Korean, "proposal": what to do, "expected": effect, "effort": "낮음"|"보통"|"높음", '
        '"action": null or {"type":"guide_topic","tool":..,"group":..,"name":English feature,"title_ko":..} or '
        '{"type":"keyword_hints","domain":D,"keywords":[...]} or {"type":"editorial_note","note":..}}],\n'
        ' "image": up to 2 promo images rendered from a brand template [{"format": "square"|"x"|"story", '
        '"kicker": tiny label <=12 chars, "headline": the big line <=28 chars (strongest benefit), "sub": <=60 chars, '
        '"points": up to 3 short bullets (square/story only), "theme": one of default|3d-dcc|game-engine|vfx|ai-3d|learn|dark, '
        '"cta": <=12 chars, "channel": where it will be posted, "caption": ready-to-paste caption, "url": page to link}],\n'
        ' "note": one Korean sentence — what you did and what you plan next.'
    )
    out = core._parse_json(core.llm(prompt, system=f"You are {role['name']} on the 3dflowhub team."
                                    + core.playbook("common", "new_staff", role["id"],
                                                    *(["designer"] if _is_designer(role) else []))
                                    + (f"\n\n=== YOUR JOB PLAYBOOK ===\n{role['playbook']}" if role.get("playbook") else ""),
                                    max_tokens=2200, json_mode=True))
    if not isinstance(out, dict):
        return {}
    now = _now()
    made = {"promo": 0, "proposal": 0, "image": 0}
    if "promo" in want:
        evs = []
        for x in (out.get("promo") or [])[:4]:
            if isinstance(x, dict) and x.get("body"):
                url = str(x.get("url") or SITE)
                url = url if url.startswith(SITE) else SITE
                ch = str(x.get("channel") or "기타")[:30]
                # 본문에 링크를 넣었으면 빼고, 채널 표시가 붙은 링크 하나만 끝에 붙인다 (중복·추적 누락 방지)
                body = str(x["body"]).replace(str(x.get("url") or ""), "").replace(url, "").strip() if x.get("url") \
                    else str(x["body"]).strip()
                evs.append({"at": now, "kind": "item", "id": "o-" + hashlib.md5(f"{now}{x['body']}".encode()).hexdigest()[:10],
                            "role": role["id"], "channel": ch, "title": core.fix_terms(str(x.get("title", "")))[:80],
                            "body": core.fix_terms(body)[:2000], "url": tracked(url, ch, role["id"])})
        if evs:
            _append(OUTBOX_PATH, *evs)
            made["promo"] = len(evs)
    if "image" in want:
        import design
        evs = []
        for x in (out.get("image") or [])[:2]:
            if not (isinstance(x, dict) and x.get("headline")):
                continue
            iid = "o-" + hashlib.md5(f"{now}{x['headline']}".encode()).hexdigest()[:10]
            fname = f"{datetime.now(timezone.utc):%Y%m%d}_{iid}"
            try:
                path = design.render_promo(x, fname)
            except Exception as e:
                core.log.warning("홍보 이미지 렌더 실패: %s", e)
                continue
            url = str(x.get("url") or SITE)
            url = url if url.startswith(SITE) else SITE
            ch = str(x.get("channel") or "인스타그램")[:30]
            evs.append({"at": now, "kind": "item", "id": iid, "role": role["id"], "channel": ch,
                        "title": core.fix_terms(str(x["headline"]))[:80],
                        "body": core.fix_terms(str(x.get("caption") or x.get("sub") or ""))[:2000],
                        "url": tracked(url, ch, role["id"]), "image": path.relative_to(core.ROOT).as_posix(),
                        "format": x.get("format", "square")})
        if evs:
            _append(OUTBOX_PATH, *evs)
            made["image"] = len(evs)
    if "proposal" in want:
        evs = []
        open_titles = {p["title"] for p in manager.board()["proposals"] if p["status"] in ("new", "held")}
        for p in (out.get("proposal") or [])[:2]:
            if isinstance(p, dict) and p.get("title") and p["title"] not in open_titles:
                evs.append({"at": now, "kind": "proposal",
                            "id": "p-" + hashlib.md5(f"{now}{p['title']}".encode()).hexdigest()[:10],
                            "title": str(p["title"])[:80], "by": role["name"],
                            "category": p.get("category") if p.get("category") in manager.CATEGORIES else "콘텐츠",
                            "evidence": core.fix_terms(str(p.get("evidence", "")))[:600],
                            "proposal": core.fix_terms(str(p.get("proposal", "")))[:900],
                            "expected": str(p.get("expected", ""))[:300],
                            "effort": p.get("effort") if p.get("effort") in ("낮음", "보통", "높음") else "보통",
                            "action": manager._valid_action(p.get("action"))})
        if evs:
            manager._append(*evs)
            made["proposal"] = len(evs)
    summary = str(out.get("note", ""))[:300]
    _append(ROLES_PATH, {"at": now, "kind": "run", "id": role["id"], "summary": summary, "made": made})
    return {"role": role["name"], **made, "note": summary}


def run_due(min_capacity: int = 20) -> list[dict]:
    """주기가 된 직원들이 일함 (AI 여력이 있을 때만, 하루 한도 안에서)."""
    if core.llm_capacity_left() < min_capacity:
        return []
    done = []
    now = datetime.now(timezone.utc)
    runs_today = [e for e in _events(ROLES_PATH) if e.get("kind") == "run" and e["at"] >= (now - timedelta(days=1)).isoformat()]
    for r in roles().values():
        if r["status"] != "active":
            continue
        if r.get("last_run") and r["last_run"] > (now - timedelta(hours=r.get("every_hours", 24))).isoformat():
            continue
        if sum(1 for e in runs_today if e["id"] == r["id"]) >= r.get("daily_calls", 2):
            continue
        try:
            done.append(run_role(r))
        except core.LLMBudgetExceeded:
            break
        except Exception as e:
            core.log.warning("직원 %s 업무 실패: %s", r.get("name"), e)
    return done
