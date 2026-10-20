"""
텔레그램 알림·휴대폰 결정 — 현황판을 열지 않아도 할 일을 받고, 버튼으로 바로 결정한다
=================================================================================
10분 수집 워크플로가 run() 을 호출한다 (AI 사용 없음, 서버 없음 — 폴링 방식).
  1) 받은 것 처리: 버튼(승인·수정 요청·거절, 제안 수락·보류·거절)과 '수정 요청' 답장 → 결정 기록
     (PR 결정은 agents.record_decision → 같은 워크플로의 apply_pr_decisions 가 GitHub 에 반영)
  2) 보낼 것 보냄: 새 승인 대기 PR · 새 제안 · 에이전트 보류 · 급한 알림 — 한 번 보낸 것은 다시 안 보냄
  3) 하루 요약: 한국 시간 아침 8시 이후 첫 실행에 한 번
보안: TELEGRAM_CHAT_ID 대화방에서 온 것만 받는다. 토큰·대화방 ID 는 GitHub Secrets 에만.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

import core

STATE = core.ROOT / "memory" / "telegram.json"
API = "https://api.telegram.org/bot{token}/{method}"
PR_LABEL = {"approve": "✅ 승인", "revise": "✏️ 수정 요청", "reject": "❌ 거절"}
PROP_LABEL = {"accepted": "✅ 수락", "held": "⏸ 보류", "rejected": "❌ 거절"}


def _cfg() -> tuple[str, str]:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()


def token_check() -> str:
    """토큰 값은 드러내지 않고 형식만 점검 — 404(Not Found)의 흔한 원인 찾기."""
    import re
    raw = os.getenv("TELEGRAM_BOT_TOKEN", "")
    t = raw.strip()
    issues = []
    if raw != t:
        issues.append("앞뒤 공백·줄바꿈 있음(자동 제거됨)")
    if t.lower().startswith("bot"):
        issues.append("앞에 'bot' 이 붙어 있음 — 빼고 등록")
    if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,50}", t.removeprefix("bot")):
        issues.append(f"형식이 '숫자:문자' 가 아님 (길이 {len(t)}, ':' {'있음' if ':' in t else '없음'})")
    return "; ".join(issues) or "형식 정상 — 토큰이 폐기(/revoke)됐거나 다른 봇의 토큰일 수 있음"


def enabled() -> bool:
    return all(_cfg())


def call(method: str, **payload) -> dict:
    token, _ = _cfg()
    r = requests.post(API.format(token=token, method=method), json=payload, timeout=30)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method}: {str(data)[:200]}")
    return data.get("result") or {}


def send(text: str, buttons: list[list[tuple[str, str]]] | None = None, **extra) -> dict:
    """buttons = [[(라벨, callback_data), ...], ...] — callback_data 는 64바이트 이하."""
    _, chat = _cfg()
    payload = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True, **extra}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                                       for row in buttons]}
    return call("sendMessage", **payload)


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────── 받기: 버튼·답장 → 결정 ───────────────────────────
def handle_update(u: dict, state: dict) -> str:
    """업데이트 하나 처리 → 사람이 읽을 결과 문구 ("" 이면 무시). 다른 대화방에서 온 것은 무시."""
    _, chat = _cfg()
    cq = u.get("callback_query")
    msg = u.get("message") or {}
    if cq:
        if str((cq.get("message") or {}).get("chat", {}).get("id")) != chat:
            return ""
        parts = (cq.get("data") or "").split(":")
        result = ""
        if len(parts) == 4 and parts[0] == "pr" and parts[3] in PR_LABEL:
            _, site, n, v = parts
            if v == "revise":  # 무엇을 고칠지 답장으로 받는다
                sent = send(f"✏️ PR #{n} 에 무엇을 고칠지 <b>이 메시지에 답장</b>으로 보내 주세요.",
                            reply_markup={"force_reply": True})
                state.setdefault("awaiting", {})[str(sent.get("message_id"))] = {"site": site, "pr": int(n)}
                result = f"PR #{n} 수정 내용 답장 기다리는 중"
            else:
                import agents
                agents.record_decision(site, int(n), v, "텔레그램에서 결정")
                result = f"PR #{n} {PR_LABEL[v]} — 10분 안에 GitHub 에 반영"
        elif len(parts) == 3 and parts[0] == "prop" and parts[2] in PROP_LABEL:
            import manager
            manager.decide(parts[1], parts[2], "텔레그램에서 결정")
            result = f"제안 {PROP_LABEL[parts[2]]}"
        if result:
            try:
                call("answerCallbackQuery", callback_query_id=cq["id"], text=result[:190])
            except RuntimeError:
                pass  # 오래된 버튼은 응답 기한이 지나도 결정은 반영됨
            m = cq.get("message") or {}
            try:
                call("editMessageReplyMarkup", chat_id=chat, message_id=m.get("message_id"), reply_markup={})
            except RuntimeError:
                pass
        return result
    if msg and str(msg.get("chat", {}).get("id")) == chat:
        reply_to = str((msg.get("reply_to_message") or {}).get("message_id", ""))
        wait = state.get("awaiting", {}).pop(reply_to, None)
        if wait and msg.get("text"):
            import agents
            agents.record_decision(wait["site"], wait["pr"], "revise", msg["text"])
            return f"PR #{wait['pr']} 수정 요청 접수 — 10분 안에 반영, 에이전트가 다시 작업"
        if (msg.get("text") or "").strip() in ("/start", "/status", "상태"):
            state["want_status"] = True
            return "상태 요청"
    return ""


def poll(state: dict) -> list[str]:
    token, _ = _cfg()
    r = requests.get(API.format(token=token, method="getUpdates"), timeout=30,
                     params={"offset": state.get("offset", 0), "timeout": 0,
                             "allowed_updates": json.dumps(["message", "callback_query"])})
    data = r.json()
    done = []
    for u in data.get("result") or []:
        state["offset"] = u["update_id"] + 1
        try:
            res = handle_update(u, state)
        except Exception as e:  # 하나가 실패해도 나머지는 처리
            res = f"처리 실패: {e}"
        if res:
            done.append(res)
    return done


# ─────────────────────────── 보내기 ───────────────────────────
def _new(state: dict, key: str) -> bool:
    sent = state.setdefault("sent", [])
    if key in sent:
        return False
    sent.append(key)
    state["sent"] = sent[-500:]
    return True


def pending_prs() -> list[dict]:
    import agents
    out = []
    for site, cfg in agents.TARGETS.items():
        try:
            prs = requests.get(f"https://api.github.com/repos/{cfg['repo']}/pulls?state=open&per_page=20",
                               timeout=20).json()
        except Exception:
            continue
        for p in prs if isinstance(prs, list) else []:
            if any(l.get("name") == "needs-approval" for l in p.get("labels") or []):
                out.append({"site": site, "number": p["number"], "title": p["title"].removeprefix("agent: ").strip(),
                            "url": p["html_url"]})
    return out


def outgoing(state: dict) -> list[tuple[str, list | None]]:
    """보낼 메시지 목록 (문구, 버튼). 이미 보낸 것은 제외."""
    import manager
    import sites
    msgs: list[tuple[str, list | None]] = []
    for p in pending_prs():
        if _new(state, f"pr:{p['site']}:{p['number']}"):
            name = sites.SITES.get(p["site"], {}).get("name", p["site"])
            msgs.append((f"🔀 <b>승인 대기 PR</b> · {esc(name)}\n#{p['number']} {esc(p['title'][:150])}\n"
                         f"<a href=\"{p['url']}/files\">바뀐 코드 보기</a>",
                         [[(PR_LABEL[v], f"pr:{p['site']}:{p['number']}:{v}") for v in ("approve", "revise", "reject")]]))
    for x in manager.board()["proposals"]:
        if x["status"] == "new" and _new(state, f"prop:{x['id']}"):
            name = sites.SITES.get(x.get("site") or "3dflowhub", {}).get("name", "")
            msgs.append((f"💡 <b>새 제안</b> · {esc(name)} · {esc(x.get('by') or 'AI 관리자')}\n<b>{esc(x['title'])}</b>\n"
                         f"{esc((x.get('proposal') or '')[:300])}"
                         + (f"\n<a href=\"{x['source']}\">근거</a>" if x.get("source") else ""),
                         [[(PROP_LABEL[v], f"prop:{x['id']}:{v}") for v in ("accepted", "held", "rejected")]]))
    for site in sites.SITES:
        for r in core._load_json(sites.site_dir(site) / "agent_runs.json", []):
            if r["result"] == "held" and _new(state, f"held:{site}:{r['at']}"):
                msgs.append((f"⏸ <b>코딩 에이전트 보류</b> · {esc(site)}\n{esc(r['task'][:150])}\n"
                             f"<i>{esc(r['msg'][:200])}</i>", None))
    try:
        import alerts
        for a in alerts.collect():
            if a.get("level") in ("error", "warning") and _new(state, f"alert:{a.get('key') or a['title']}:{_now()[:10]}"):
                msgs.append((f"⚠️ <b>{esc(a['title'])}</b>\n{esc(a.get('detail', ''))[:300]}", None))
    except Exception:
        pass
    return msgs


def daily_summary() -> str:
    import manager
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {}).get("pages") or {}
    daily = perf.get("daily") or {}
    yday = sorted(daily)[-2] if len(daily) >= 2 else ""
    dn = manager.done_today()
    waiting = sum(1 for x in manager.board()["proposals"] if x["status"] == "new")
    return (f"🌅 <b>3dflowhub 아침 요약</b>\n"
            f"방문: 어제 {daily.get(yday, '-')}회 · 30일 {perf.get('pv_30d', '-')}회\n"
            f"오늘 만든 것: 소식 {dn['news']} · 가이드 {dn['guides']} · 정리 {dn['roundups']}\n"
            f"결정 대기 제안 {waiting}건 · AI 남은 여력 {core.llm_capacity_left()}회")


def run() -> dict:
    """10분 워크플로에서 호출. 결과·오류를 항상 memory/telegram.json 의 last_run 에 남긴다."""
    state = core._load_json(STATE, {})
    if not enabled():
        token, chat = _cfg()
        out = {"skipped": "비밀값 없음: " + ", ".join(n for n, v in (("TELEGRAM_BOT_TOKEN", token),
                                                                    ("TELEGRAM_CHAT_ID", chat)) if not v)}
        state["last_run"] = {"at": _now(), **out}
        core._save_json(STATE, state)
        return out
    try:
        out = _run(state)
    except Exception as e:  # 오류도 기록 (토큰 문자열은 남기지 않음)
        token, _ = _cfg()
        out = {"error": f"{type(e).__name__}: {str(e).replace(token, '***')[:300]}", "token_check": token_check()}
    state["last_run"] = {"at": _now(), **{k: v for k, v in out.items() if k != "received"},
                         "received": len(out.get("received", []))}
    core._save_json(STATE, state)
    return out


def _run(state: dict) -> dict:
    out: dict = {"received": [], "sent": 0}
    first = not state.get("hello")
    if first:
        send("✅ <b>3dflowhub 알림 연결됨</b>\n승인 대기 PR·새 제안·문제가 생기면 여기로 알려 드리고, "
             "버튼으로 바로 결정할 수 있어요 (10분 안에 반영). '상태'라고 보내면 지금 요약을 보내 드립니다.")
        state["hello"] = _now()
    try:
        out["received"] = poll(state)
    except Exception as e:
        out["poll_error"] = str(e)[:200]
    pending = outgoing(state)
    if first:  # 처음엔 이미 쌓인 제안·알림을 쏟아내지 않고 '본 것'으로 처리, 승인 대기 PR 만
        pending = [m for m in pending if m[0].startswith("🔀")]
    for text, buttons in pending[:15]:  # 한 번에 너무 많이 보내지 않게
        try:
            send(text, buttons)
            out["sent"] += 1
        except Exception as e:
            out.setdefault("errors", []).append(str(e)[:120])
    from zoneinfo import ZoneInfo
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    if state.pop("want_status", False) or (kst.hour >= 8 and state.get("summary_day") != kst.date().isoformat()):
        send(daily_summary())
        state["summary_day"] = kst.date().isoformat()
        out["summary"] = True
    for r in out["received"]:
        if r and r != "상태 요청":
            send(f"👌 {esc(r)}")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
