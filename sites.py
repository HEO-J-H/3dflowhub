"""HQ(본사) — 여러 사이트를 한 엔진·한 현황판으로 운영.

3dflowhub 저장소가 본사: AI 키·AI 관리자·직원·교본·현황판을 공유하고, 각 사이트는 '소속 사이트(site)'로 구분한다.
- 3dflowhub   : 이 저장소가 직접 만드는 큐레이션 사이트 (수집·가이드·배포까지 자동)
- life-after-60: 다른 저장소의 은퇴 현금흐름 시뮬레이터 (정적 앱). 법규·계산식은 '제안·PR 만', 머지는 사람.
사이트별 산출물(점검 결과·규정 감시)은 memory/sites/<site>/ 에 저장.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

import core

SITES: dict[str, dict] = {
    "3dflowhub": {
        "name": "🧊 3dflowhub", "url": "https://heo-j-h.github.io/3dflowhub/", "repo": "HEO-J-H/3dflowhub",
        "kind": "curation", "about": "3D·게임엔진·VFX·AI 3D 소식과 기초 가이드 (한국어 큐레이션·학습 사이트)",
    },
    "life-after-60": {
        "name": "💰 life-after-60", "url": "https://heo-j-h.github.io/life-after-60/", "repo": "HEO-J-H/life-after-60",
        "kind": "app", "about": "60세 은퇴 목표 자산·연금·ISA·세금을 반영한 월별 현금흐름 시뮬레이터 (브라우저 로컬 계산)",
        "raw": "https://raw.githubusercontent.com/HEO-J-H/life-after-60/main/",
        "rules": "법규·세무·계산식·시뮬 로직은 자동 변경 금지 — 제안 또는 PR 만, 머지는 사람. "
                 "도구 안내용이며 법률·투자 자문이 아님을 항상 유지.",
    },
}
DEFAULT_SITE = "3dflowhub"
UA = {"User-Agent": "Mozilla/5.0 (3dflowhub HQ monitor)"}


def site_dir(site: str):
    d = core.ROOT / "memory" / "sites" / site
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_text(url: str, timeout: int = 20) -> str:
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text


# ─────────────────────────── life-after-60: 상태 점검 (AI 없음) ───────────────────────────
def regulatory_source(site: str = "life-after-60") -> str:
    return fetch_text(SITES[site]["raw"] + "regulatory-reference.js")


def review_stamp(js: str) -> str:
    m = re.search(r"REVIEW_STAMP\s*=\s*'(\d{4}-\d{2}-\d{2})'", js)
    return m.group(1) if m else ""


def health_check(site: str = "life-after-60") -> dict:
    """사이트 응답·참고 링크 깨짐·규정 검토일 경과를 점검해 memory/sites/<site>/health.json 에 기록."""
    s = SITES[site]
    out: dict = {"at": datetime.now(timezone.utc).isoformat(), "site": site, "problems": []}
    try:
        r = requests.get(s["url"], headers=UA, timeout=20)
        out["status"] = r.status_code
        out["bytes"] = len(r.content)
        if r.status_code != 200:
            out["problems"].append(f"사이트 응답 {r.status_code}")
    except requests.RequestException as e:
        out["status"] = 0
        out["problems"].append(f"사이트 접속 실패: {type(e).__name__}")
    try:
        js = regulatory_source(site)
        stamp = review_stamp(js)
        out["review_stamp"] = stamp
        if stamp:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(stamp).date()).days
            out["review_age_days"] = age
            if age > 90:
                out["problems"].append(f"규정 요약 검토일이 {age}일 지남 (REVIEW_STAMP {stamp})")
        links = sorted(set(re.findall(r"https?://[^'\"\s)<>]+", js)))
        broken = []
        for u in links[:60]:
            try:
                rr = requests.head(u, headers=UA, timeout=12, allow_redirects=True)
                if rr.status_code >= 400 and rr.status_code not in (403, 405, 429):  # 403/405: HEAD 거부하는 정부 사이트 많음
                    rr = requests.get(u, headers=UA, timeout=15, allow_redirects=True)
                if rr.status_code in (404, 410) or rr.status_code >= 500:
                    broken.append({"url": u, "status": rr.status_code, "sure": True})  # 확실히 깨짐
                elif rr.status_code >= 400 and rr.status_code not in (403, 405, 429):
                    broken.append({"url": u, "status": rr.status_code, "sure": False})
            except requests.RequestException as e:  # 정부 사이트는 해외 서버 접속을 막는 경우가 많아 '확인 필요'로만
                broken.append({"url": u, "status": type(e).__name__, "sure": False})
        out["links_checked"] = len(links)
        out["broken_links"] = broken
        sure = [b for b in broken if b["sure"]]
        if sure:
            out["problems"].append(f"참고 링크 {len(sure)}개 깨짐 (404 등)")
    except requests.RequestException as e:
        out["problems"].append(f"regulatory-reference.js 읽기 실패: {type(e).__name__}")
    core._save_json(site_dir(site) / "health.json", out)
    return out


def last_health(site: str = "life-after-60") -> dict:
    return core._load_json(site_dir(site) / "health.json", {})


# ─────────────────────────── life-after-60: 규정 감시 자료 ───────────────────────────
REG_QUERIES = ["국민연금 개정", "기초연금 인상", "연금소득세 분리과세", "ISA 세제 개편", "연금저축 세액공제 한도",
               "퇴직소득세 개정", "건강보험료 피부양자 기준", "금융소득 종합과세 기준", "IRP 퇴직연금 제도 변경"]


def regulatory_digest(js: str, limit: int = 4500) -> str:
    """regulatory-reference.js 에서 숫자가 들어간 한국어 안내 문장만 추려 요약 (AI 에 보여줄 현재 사이트 기준)."""
    texts = re.findall(r"'([^'\n]{12,400})'", js) + re.findall(r'"([^"\n]{12,400})"', js)
    keep = []
    for t in texts:
        t = re.sub(r"<[^>]+>", "", t).strip()
        if re.search(r"[가-힣]", t) and re.search(r"\d", t) and t not in keep:
            keep.append(t)
    return "\n".join(f"- {t}" for t in keep)[:limit]


def regulatory_news(days: int = 21, per_query: int = 4) -> list[dict]:
    """공식 발표·언론 보도 제목 (구글 뉴스 RSS) — 개정 가능성이 있는 항목을 찾는 단서."""
    import feedparser
    from urllib.parse import quote
    out, seen = [], set()
    for q in REG_QUERIES:
        try:
            feed = core.fetch_feed(f"https://news.google.com/rss/search?q={quote(q + ' when:' + str(days) + 'd')}"
                                   "&hl=ko&gl=KR&ceid=KR:ko")
        except Exception:
            continue
        for e in feed.entries[:per_query]:
            t = e.get("title", "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append({"query": q, "title": t[:160], "link": e.get("link", ""), "date": e.get("published", "")[:16]})
    _ = feedparser  # fetch_feed 내부 사용
    return out
