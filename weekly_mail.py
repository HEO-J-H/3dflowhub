"""주간 요약 메일 — 매주 월요일 아침(한국 시간) 구독자에게 Buttondown 으로 자동 발송.

전에는 구독 신청만 받고 실제 메일은 보내지 않았음 (2026-11-17 사장님 확인).
- 키: GitHub Secrets 의 BUTTONDOWN_API_KEY (없으면 아무것도 보내지 않음)
- 한 주에 한 번만 (memory/strategy.json 의 weekly_mail_week 에 ISO 주차 기록)
- 내용: 지난주 추천 소식 · 새 기초 가이드 · 마감 임박 공모전 · 이번 주 작품 + 사이트 주간 요약 링크
- AI 를 쓰지 않음 (이미 사이트에 있는 요약·제목만 모음)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import core

KST = timezone(timedelta(hours=9))
API = "https://api.buttondown.com/v1/emails"
SEND_HOUR_KST = 8  # 월요일 오전 8시 이후 첫 실행에서 발송


def _at(x: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((x or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def last_week(now: datetime) -> tuple[datetime, datetime, str]:
    """지난주 월요일 00:00 ~ 이번 주 월요일 00:00 (한국 시간), 지난주 ISO 주차."""
    monday = (now.astimezone(KST) - timedelta(days=now.astimezone(KST).weekday())).replace(hour=0, minute=0, second=0,
                                                                                         microsecond=0)
    start = monday - timedelta(days=7)
    y, w, _ = start.isocalendar()
    return start, monday, f"{y}-W{w:02d}"


def compose(now: datetime | None = None) -> dict | None:
    """보낼 메일 {subject, body(markdown), week}. 담을 것이 너무 적으면 None."""
    import build_site as bs
    import events
    import guides
    import showcase

    now = now or datetime.now(timezone.utc)
    start, end, week = last_week(now)
    base = bs.BASE_URL
    utm = "?utm_source=newsletter&utm_campaign=weekly-" + week

    def inside(x: str | None) -> bool:
        t = _at(x)
        return bool(t) and start <= t.astimezone(KST) < end

    week_posts = [p for p in bs.load_posts() if inside(p.get("collected_at")) and not bs.is_thin(p)]
    views = bs.page_views()
    # 추천(pick) 글 먼저, 그다음 많이 본 글·그림 있는 글 (추천이 적은 주에도 소식이 비지 않게)
    posts = sorted(week_posts, key=lambda p: (not p.get("pick"), -views.get(p["id"], 0),
                                              not (p.get("media") or {}).get("image")))
    new_guides = [g for g in guides.load_all() if inside(g.get("at"))][:6]
    today = now.astimezone(KST).date()
    soon = []
    for ev in events.load_all():
        try:
            d = datetime.strptime(ev.get("deadline") or "", "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= d <= today + timedelta(days=14):
            soon.append((d, ev))
    soon.sort(key=lambda x: x[0])
    works = showcase.auto_items()[:2]
    if len(posts) + len(new_guides) < 3:
        return None

    lines = [f"안녕하세요, 3dflowhub 입니다. {start:%m월 %d일}부터 일주일 동안 정리한 3D 소식과 새 가이드를 모았어요.", ""]
    if posts:
        lines += ["## 📰 지난주 꼭 볼 소식", ""]
        for p in posts[:8]:
            title = p.get("title_ko") or p.get("title") or ""
            lines.append(f"- **[{title}]({base}/p/{p['id']}.html{utm})** — {(p.get('summary') or '').strip()[:120]}")
        lines.append("")
    if new_guides:
        lines += ["## 📚 새로 올라온 기초 가이드", ""]
        lines += [f"- [{g.get('tool', '')} · {g.get('title', '')}]({base}/{bs.learn_url(g)}{utm})" for g in new_guides]
        lines.append("")
    if soon:
        lines += ["## 🏆 마감이 다가오는 공모전·게임 잼", ""]
        lines += [f"- {d:%m월 %d일} 마감 · [{ev.get('title', '')}]({ev.get('url', '')}) ({ev.get('kind', '')}, {ev.get('region', '')})"
                  for d, ev in soon[:5]]
        lines += [f"- 전체 일정: {base}/events/{utm}", ""]
    if works:
        lines += ["## 🎨 이번 주 작품", ""]
        lines += [f"- [{w['title']}]({w['url']}) — {w['artist']} · 👀 {w.get('note', '')}" for w in works]
        lines += [f"- 3D로 돌려 보기: {base}/showcase/{utm}", ""]
    lines += [f"지난주 전체 요약은 [사이트 주간 요약]({base}/weekly/{week}/{utm})에서 볼 수 있어요.", "",
              "궁금한 점이나 다뤄 줬으면 하는 주제가 있으면 이 메일에 답장해 주세요.", "", "고맙습니다. 3dflowhub 드림"]
    subject = f"[3dflowhub] {start:%m월 %d일} 주간 3D 소식 — 소식 {len(posts[:8])}개 · 새 가이드 {len(new_guides)}개"
    return {"subject": subject, "body": "\n".join(lines), "week": week}


def due(now: datetime, strategy: dict) -> bool:
    k = now.astimezone(KST)
    _, _, week = last_week(now)
    return k.weekday() == 0 and k.hour >= SEND_HOUR_KST and strategy.get("weekly_mail_week") != week


def run(now: datetime | None = None, dry: bool = False) -> str:
    """조건이 맞으면 발송. 결과 한 줄을 돌려준다 (로그·현황판용)."""
    import requests

    now = now or datetime.now(timezone.utc)
    strategy = core.load_strategy()
    if not dry and not due(now, strategy):
        return "발송 시각 아님"
    key = os.getenv("BUTTONDOWN_API_KEY", "").strip()
    if not key and not dry:
        return "BUTTONDOWN_API_KEY 없음 — 발송 안 함"
    mail = compose(now)
    if not mail:
        msg = "지난주 담을 글이 너무 적어 건너뜀"
    elif dry:
        return mail["subject"] + "\n\n" + mail["body"]
    else:
        r = requests.post(API, timeout=30, json={"subject": mail["subject"], "body": mail["body"], "status": "about_to_send"},
                          headers={"Authorization": f"Token {key}", "X-Buttondown-Live-Dangerously": "true"})
        if not r.ok:
            msg = f"발송 실패 HTTP {r.status_code}: {r.text[:200]}"
            strategy["weekly_mail_note"] = msg
            core._save_json(core.STRATEGY_PATH, strategy)
            return msg  # 실패는 주차를 기록하지 않음 → 다음 실행에서 다시 시도
        msg = f"발송 완료: {mail['subject']}"
    strategy = core.load_strategy()
    strategy["weekly_mail_week"] = last_week(now)[2]
    strategy["weekly_mail_note"] = msg
    core._save_json(core.STRATEGY_PATH, strategy)
    return msg


if __name__ == "__main__":
    import sys
    print(run(dry="--dry" in sys.argv))
