"""
사이트별 AI 관리자 — 3dflowhub 외 사이트(🧱 Pix2Poly, 💰 life-after-60)마다 따로 판단하는 팀장
==========================================================================================
3dflowhub 관리자(manager.review)는 뉴스·가이드 지표를 보고, 이 관리자는 각 사이트 자기 자료만 본다.
  - 🧱 Pix2Poly: 코딩 에이전트 기록·대기열(.agent/TODO.md)·승인 대기 PR·테스트·기술 동향 제안·웹 버전
  - 💰 life-after-60: 상태 점검·규정 감시·홍보 반응·사람의 결정
하는 일: 하루 1회 상황 요약 + 다음에 할 일 제안(최대 3개, 사이트 소속) + 사장님 메시지에 답변.
제안은 기존 제안 보드에 사이트 이름표를 달아 올리고(수락하면 코딩 에이전트·직원이 처리), 요약은 사이트 폴더에 저장.

AI 한도: 뉴스 수집 몫(core.NEWS_RESERVE)을 남기고 여유가 있을 때만 (core.background_ok), 사이트당 하루 1회.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import core

EVERY = timedelta(hours=24)
MAX_PROPOSALS = 3
NEED_CALLS = 5          # 실행 조건: 뉴스 몫을 남기고 이만큼 여유
SITES_WITH_MANAGER = ("pix2poly", "life-after-60")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def report_path(site: str):
    import sites
    return sites.site_dir(site) / "manager_report.json"


def last_report(site: str) -> dict:
    return core._load_json(report_path(site), {})


def _context(site: str) -> dict:
    """사이트별로 관리자가 볼 자료 (AI 호출 없이 모음)."""
    import manager
    import sites
    s = sites.SITES[site]
    ctx: dict = {"site": {k: s.get(k) for k in ("name", "url", "about", "rules", "kind")}}
    props = [p for p in manager.board()["proposals"] if (p.get("site") or "3dflowhub") == site]
    ctx["open_proposals"] = [p["title"] for p in props if p["status"] in ("new", "held")]
    ctx["owner_decisions"] = [{"title": p["title"], "decision": manager.STATUS_KO[p["status"]], "reason": p.get("note", ""),
                               "by": p.get("by")} for p in props if p["status"] != "new"][:15]
    ctx["accepted_work"] = [p["title"] for p in manager.manual_todo(site)]
    try:
        import staff
        ctx["team"] = [{"name": r["name"], "status": r["status"], "every_hours": r.get("every_hours"),
                        "last": (r.get("last") or {}).get("note", "")[:160]}
                       for r in staff.roles().values() if r.get("site") == site]
    except Exception:
        ctx["team"] = []
    if s.get("kind") == "tool":
        ctx["agent_runs"] = core._load_json(sites.site_dir(site) / "agent_runs.json", [])[-8:]
        ctx["pending_pr_decisions"] = [d for d in core._load_json(sites.site_dir(site) / "pr_decisions.json", [])
                                       if not d.get("done")]
        try:
            import requests
            r = requests.get(f"https://api.github.com/repos/{s['repo']}/contents/.agent/TODO.md", timeout=15).json()
            import base64
            todo = base64.b64decode(r.get("content", "")).decode("utf-8")
            ctx["agent_queue"] = [l[:160] for l in todo.splitlines() if l.startswith("- [")][-12:]
            prs = requests.get(f"https://api.github.com/repos/{s['repo']}/pulls?state=open", timeout=15).json()
            ctx["open_prs"] = [p["title"][:100] for p in prs] if isinstance(prs, list) else []
        except Exception:
            pass
    else:
        h = sites.last_health(site)
        ctx["health"] = {k: v for k, v in h.items() if k != "broken_links"}
        ctx["broken_links"] = len([b for b in h.get("broken_links") or [] if b.get("sure")])
        try:
            import staff
            ctx["promo"] = [{"channel": x.get("channel"), "status": x.get("status"), "title": x.get("title", "")[:60]}
                            for x in staff.outbox() if (x.get("site") or "3dflowhub") == site][-10:]
        except Exception:
            pass
    return ctx


def due(site: str, force: bool = False) -> bool:
    last = last_report(site).get("at", "")
    pending = [m for m in messages(site) if not m.get("reply")]
    return force or bool(pending) or not last or last < (datetime.now(timezone.utc) - EVERY).isoformat()


def messages(site: str) -> list[dict]:
    return last_report(site).get("messages", [])


def send_message(site: str, text: str) -> None:
    """사장님 → 이 사이트 관리자. 다음 실행 때 답한다."""
    rep = last_report(site)
    rep.setdefault("messages", []).append({"at": _now(), "text": text.strip()[:1000], "reply": None})
    rep["messages"] = rep["messages"][-20:]
    core._save_json(report_path(site), rep)


def review(site: str, force: bool = False) -> dict | None:
    """하루 1회(또는 메시지가 오면): 요약·제안·답변. 뉴스 몫을 남기고 여유가 있을 때만 (AI 1회)."""
    import manager
    import sites
    if not (due(site, force) and core.background_ok(NEED_CALLS)):
        return None
    s = sites.SITES[site]
    ctx = _context(site)
    rep = last_report(site)  # 답변을 같은 객체에 적어 저장하려고 한 번만 읽음
    pending = [m for m in rep.get("messages", []) if not m.get("reply")]
    kind_rules = ("This is a CODE TOOL repo. A coding agent implements accepted proposals every 3 hours (tests first; "
                  "low-risk changes auto-merge, core pipeline changes become PRs the owner approves). Propose SMALL, "
                  "testable work naming the exact files, unblock stuck/held tasks (split them, or say what the owner must "
                  "decide), and point out PRs waiting for approval. Large features need a design guide first."
                  if s.get("kind") == "tool" else
                  "This is a STATIC APP whose laws/formulas are never changed automatically — propose review items with "
                  "official sources, UX/accessibility for 50-60s readers, broken-link fixes and promotion ideas. "
                  "Never give legal, tax or investment advice.")
    prompt = (
        f"You are the AI manager (team lead) dedicated to {s['name']} ({s['url']}) — {s['about']}.\n"
        f"Rules: {s.get('rules', '')}\n{kind_rules}\n"
        f"Current situation: {json.dumps(ctx, ensure_ascii=False, default=str)[:7000]}\n"
        f"Owner's messages to answer: {json.dumps([{'i': i, 'text': m['text']} for i, m in enumerate(pending)], ensure_ascii=False)}\n"
        "Do not repeat rejected ideas unless the reason is addressed; do not duplicate open proposals.\n"
        "Return JSON in Korean:\n"
        ' "summary": 2-3 sentences on this site\'s state today, citing concrete facts from the situation,\n'
        f' "proposals": up to {MAX_PROPOSALS} items [{{"title": <=40 chars, "category": one of {manager.CATEGORIES}, '
        '"evidence": facts from the situation, "proposal": what to do concretely (files/steps), "expected": effect, '
        '"effort": "낮음"|"보통"|"높음", "source": a real URL from the situation or ""}],\n'
        ' "replies": [{"i": message index, "text": answer}],\n'
        ' "watch": one sentence — what you will check next time'
    )
    out = core._parse_json(core.llm(prompt, system=f"You are the dedicated AI manager of {s['name']}."
                                    + core.playbook("common", "manager", f"site_{site}"), max_tokens=1600, json_mode=True))
    if not isinstance(out, dict):
        return None
    now = _now()
    evs = []
    for p in (out.get("proposals") or [])[:MAX_PROPOSALS]:
        if not isinstance(p, dict) or not p.get("title") or manager.similar_open(str(p["title"]), site):
            continue
        evs.append({"at": now, "kind": "proposal", "id": "p-" + hashlib.md5(f"{now}{site}{p['title']}".encode()).hexdigest()[:10],
                    "title": str(p["title"])[:80], "by": f"🧭 {s['name']} 관리자", "site": site,
                    "category": p.get("category") if p.get("category") in manager.CATEGORIES else "운영·비용",
                    "evidence": core.fix_terms(str(p.get("evidence", "")))[:600],
                    "proposal": core.fix_terms(str(p.get("proposal", "")))[:900],
                    "expected": str(p.get("expected", ""))[:300],
                    "effort": p.get("effort") if p.get("effort") in ("낮음", "보통", "높음") else "보통",
                    "source": str(p.get("source") or "")[:300], "action": None, "risk": "medium"})
    if evs:
        manager._append(*evs)
    for r in out.get("replies") or []:
        try:
            pending[int(r["i"])]["reply"] = str(r["text"])[:1500]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    rep.update({"at": now, "summary": core.fix_terms(str(out.get("summary", "")))[:800],
                "watch": str(out.get("watch", ""))[:300], "proposals": [e["title"] for e in evs]})
    core._save_json(report_path(site), rep)
    return rep


def run_due() -> list[str]:
    """evolve 가 매 실행 호출 — 주기가 된 사이트 관리자만 일함."""
    done = []
    for site in SITES_WITH_MANAGER:
        try:
            r = review(site)
        except core.LLMBudgetExceeded:
            break
        except Exception as e:
            core.log.warning("%s 관리자 실패: %s", site, e)
            continue
        if r:
            done.append(f"{site}: 제안 {len(r.get('proposals', []))}개")
    return done
