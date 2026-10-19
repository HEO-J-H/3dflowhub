"""
3dflowhub 수익화 학습 — 성과(조회수·유입·키워드·광고수익) 수집 → 노션 기록 → evolve 가 학습
================================================================================================
이 PC 전용 (티스토리 로그인 세션 필요):  python monetize.py
  1) 티스토리 관리 통계 API(/manage/v2/statistics/blog/*) 에서 글별 조회수, 검색 키워드, 유입 경로 수집
  2) 노션 각 글의 Views(조회수) 속성 갱신 → GitHub Actions 의 evolve 가 노션에서 읽어 '보상 신호'로 학습
  3) memory/performance.json 에 일별 스냅샷 저장 (대시보드 표시용) + 광고수익(revenue.csv)과 결합해 RPM 계산

애드센스 정책 준수: 자기 광고 클릭 유도·자동 클릭·광고 근처 버튼 배치 등은 절대 하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import core

PERF_PATH = core.ROOT / "memory" / "performance.json"
REVENUE_CSV = core.ROOT / "memory" / "revenue.csv"
STATS = f"https://{core.TISTORY_BLOG_NAME}.tistory.com/manage/v2/statistics/blog/"


def fetch_tistory_stats(days: int = 30) -> dict:
    """로그인된 브라우저 세션으로 티스토리 통계 JSON 수집."""
    from playwright.sync_api import sync_playwright

    import tistory_publisher as tp
    start = date.today().replace(day=1).isoformat()
    out: dict = {}
    with sync_playwright() as p:
        ctx = tp._launch(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://{core.TISTORY_BLOG_NAME}.tistory.com/manage/statistics/blog", wait_until="domcontentloaded")
        if "login" in page.url:
            ctx.close()
            raise SystemExit("티스토리 로그인이 필요합니다: 티스토리_로그인.bat")

        def get(path: str):
            r = ctx.request.get(STATS + path)
            return r.json().get("data", {}).get("result") if r.ok else None

        out["count"] = get("count")
        out["inflow"] = get(f"inflow?granularity=month&metric=pv&startDate={start}")
        out["keywords"] = get(f"keyword?granularity=month&metric=pv&startDate={start}") or []
        # 글별 누적 조회수: 최근 N일 일간 topEntry 를 합산 (월 단위는 이번 달만 집계되므로)
        views: dict[str, dict] = {}
        for i in range(days):
            day = (date.today() - timedelta(days=i)).isoformat()
            for e in get(f"topEntry?metric=pv&startDate={day}&granularity=day") or []:
                if not isinstance(e, dict) or not e.get("permalink"):
                    continue
                v = views.setdefault(e["permalink"], {"title": e.get("title", ""), "created": e.get("created", ""),
                                                      "views": 0})
                v["views"] += e.get("count", 0)
        out["posts"] = views
        ctx.close()
    return out


def revenue_summary() -> dict:
    if not REVENUE_CSV.exists():
        return {"total": 0.0, "last30": 0.0}
    rev = pd.read_csv(REVENUE_CSV, parse_dates=["date"])
    recent = rev[rev["date"] >= pd.Timestamp(date.today() - timedelta(days=30))]
    return {"total": float(rev["revenue"].sum()), "last30": float(recent["revenue"].sum())}


def sync_views_to_notion(posts: dict) -> int:
    """노션 페이지(TistoryURL 일치)의 Views 속성 갱신."""
    client = core._notion()
    if client is None:
        return 0
    n = 0
    for url, info in posts.items():
        res = core._query_db(client, {"page_size": 1, "filter": {"property": "TistoryURL", "url": {"equals": url}}})
        for p in res.get("results", []):
            client.pages.update(page_id=p["id"], properties={"Views": {"number": info["views"]}})
            n += 1
    return n


GC_TOKEN = os.getenv("GOATCOUNTER_TOKEN", "")


def fetch_pages_stats(days: int = 30) -> dict | None:
    """GitHub Pages 방문 통계 (GoatCounter API). 설정이 없으면 None. CI 에서도 동작 (로그인 불필요)."""
    import requests
    code = (core._load_json(core.CONFIG_PATH, {}).get("goatcounter_code") or "").strip()
    if not (code and GC_TOKEN):
        return None
    api = f"https://{code}.goatcounter.com/api/v0"
    h = {"Authorization": f"Bearer {GC_TOKEN}", "Content-Type": "application/json"}
    start = f"{date.today() - timedelta(days=days)}T00:00:00Z"  # RFC3339

    def get(path: str, **params) -> dict:
        r = requests.get(f"{api}{path}", params={"start": start, **params}, headers=h, timeout=20)
        r.raise_for_status()  # 401/429/5xx 를 0건으로 오인해 기존 통계를 덮어쓰지 않도록
        return r.json()

    total = get("/stats/total")
    refs = get("/stats/toprefs", limit=10)
    posts, rows, exclude = {}, [], []
    for _ in range(20):  # hits 는 한 번에 최대 100개 → 'more' 동안 이어받기 (최대 2,000 경로)
        page = get("/stats/hits", limit=100, **({"exclude_paths": ",".join(map(str, exclude))} if exclude else {}))
        batch = page.get("hits") or []
        rows += batch
        exclude += [r.get("path_id") for r in batch if r.get("path_id") is not None]
        if not page.get("more") or not batch:
            break
    learn: dict[str, dict] = {}
    by_kind = {"news": 0, "guides": 0, "roundups": 0, "other": 0}  # 콘텐츠 종류별 조회수 (자동 모드 배분 판단용)
    for row in rows:
        path, n = row.get("path", ""), int(row.get("count", 0))
        m = re.search(r"/p/([^/]+)\.html$", path)
        g = re.search(r"/learn/([^/]+)/?$", path)
        if m:
            posts[m.group(1)] = {"title": row.get("title", ""), "views": n}
            by_kind["news"] += n
        elif g:
            learn[g.group(1)] = {"title": row.get("title", ""), "views": n}
            by_kind["guides"] += n
        elif "/guide/" in path:
            by_kind["roundups"] += n
        else:
            by_kind["other"] += n
    daily = {str(d.get("day", ""))[:10]: int(d.get("daily", 0)) for d in total.get("stats") or [] if d.get("day")}
    return {"at": datetime.now().isoformat(timespec="seconds"), "pv_30d": int(total.get("total", 0)),
            "daily": daily,  # 날짜별 조회수 (현황판 수집 추이 차트에 함께 표시)
            "posts": posts, "learn": learn, "by_kind": by_kind,
            "refs": [(r.get("name") or "(직접)", r.get("count", 0)) for r in refs.get("stats", [])]}


def sync_pages_views_to_notion() -> int:
    """GitHub Pages 조회수를 티스토리 조회수와 합쳐 노션 Views 로 기록."""
    client = core._notion()
    if client is None:
        return 0
    perf = core._load_json(PERF_PATH, {})
    tistory_by_title = {v["title"]: v["views"] for v in (perf.get("latest") or {}).get("posts", {}).values()}
    n = 0
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        pv = (perf.get("pages") or {}).get("posts", {}).get(f.stem, {}).get("views", 0)
        if p.get("notion_id") and pv:
            total = pv + tistory_by_title.get(p.get("title_ko", ""), 0)
            client.pages.update(page_id=p["notion_id"], properties={"Views": {"number": total}})
            n += 1
    return n


def collect_pages() -> dict | None:
    """GitHub Pages 성과만 수집 (CI 의 evolve 단계에서 호출)."""
    stats = fetch_pages_stats()
    if stats is None:
        return None
    perf = core._load_json(PERF_PATH, {"snapshots": []})
    perf["pages"] = stats
    perf["pages_snapshots"] = (perf.get("pages_snapshots", []) + [{"at": stats["at"], "pv_30d": stats["pv_30d"]}])[-120:]
    core._save_json(PERF_PATH, perf)
    stats["notion_updated"] = sync_pages_views_to_notion()
    return stats


def collect() -> dict:
    try:
        collect_pages()
    except Exception as e:  # GoatCounter 미설정·오류여도 티스토리 수집은 계속
        print("Pages 통계 수집 실패:", str(e)[:150])
    stats = fetch_tistory_stats()
    pv30 = sum(p["views"] for p in stats["posts"].values())
    rev = revenue_summary()
    snapshot = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "pv_total": (stats.get("count") or {}).get("pv", {}).get("total", 0),
        "pv_30d_posts": pv30,
        "revenue_30d": rev["last30"],
        "rpm_30d": round(rev["last30"] / pv30 * 1000, 1) if pv30 else 0.0,  # 1,000뷰당 수익
        "inflow": stats.get("inflow"),
        "keywords": stats.get("keywords")[:30],
        "posts": stats["posts"],
    }
    perf = core._load_json(PERF_PATH, {"snapshots": []})
    perf["latest"] = snapshot
    perf["snapshots"] = (perf["snapshots"] + [{k: snapshot[k] for k in ("at", "pv_total", "pv_30d_posts",
                                                                     "revenue_30d", "rpm_30d")}])[-120:]
    core._save_json(PERF_PATH, perf)
    snapshot["notion_updated"] = sync_views_to_notion(stats["posts"])
    return snapshot


if __name__ == "__main__":
    s = collect()
    print(json.dumps({k: s[k] for k in ("pv_total", "pv_30d_posts", "revenue_30d", "rpm_30d", "notion_updated")},
                     ensure_ascii=False))
