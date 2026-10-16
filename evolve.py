"""
3dflowhub 자율 진화 루프 — [4] 피드백·자아 성찰 → [5] 프롬프트/전략 자동 업데이트
====================================================================================
매 수집 실행 끝에 core.run_pipeline 이 evolve(stats) 를 호출한다.

  update_strategy()  (6시간마다)  Reflexion 방식의 '언어적 피드백'
      - 최근 실행 통계·오류·카테고리 분포를 LLM 이 성찰 → 편집 가이드(prompt_notes),
        도메인별 검색 힌트(keyword_hints), 새 RSS 후보를 memory/strategy.json 에 기록
      - 3회 연속 0건인 피드는 자동 차단, LLM 이 제안한 새 피드는 실제로 파싱되는 것만 추가
  refine_taxonomy()  (24시간마다)  TNT-LLM 방식의 카테고리 체계 정제
      - 세부 카테고리 목록·사용 빈도를 보고 중복/유사 카테고리를 병합 → memory + 노션 반영

참고: Reflexion (Shinn et al., 2023), TextGrad (Yuksekgonul et al., 2024), TNT-LLM (Wan et al., 2024)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import feedparser

import core

log = core.log
STRATEGY_EVERY = 6 * 3600
TAXONOMY_EVERY = 24 * 3600
MAX_NOTES = 6
MAX_EXTRA_FEEDS = 4  # 도메인별 자동 추가 피드 상한
BLOCK_AFTER_EMPTY = 3


# 수익화 플레이북 — 성찰 때마다 LLM 에 주입되는 '학습된 원칙' (Google 검색·애드센스 공개 가이드 기반)
MONETIZATION_PLAYBOOK = [
    "애드센스 수익 = 페이지뷰 × RPM. 검색 유입(구글·네이버·다음)이 핵심이므로 검색 의도에 맞는 제목·본문이 최우선",
    "제목: 핵심 도구/제품명 + 검색 키워드를 앞쪽에 (25~45자), 낚시성 제목 금지",
    "사람에게 도움이 되는 독창적 콘텐츠: 요약만이 아니라 실무 적용법·의견·비교를 추가 (저품질·가치 낮은 콘텐츠 거절 방지)",
    "충분한 분량(본문 1,500자 이상)·소제목 구조·FAQ 로 체류시간과 검색 스니펫 노출을 늘린다",
    "같은 카테고리 관련 글 내부 링크로 방문당 페이지뷰를 늘린다",
    "고단가(CPC) 주제: 소프트웨어 출시·가격·비교, 하드웨어(GPU), 튜토리얼, 강의/교육 — 조회수 데이터와 함께 비중 조정",
    "꾸준한 발행(하루 1~3개) 유지, 대량 자동 발행 금지",
    "정책: 광고 클릭 유도 문구·자기 클릭·광고 옆 버튼 배치·저작권 침해 금지 (계정 정지 위험)",
]


def performance_table() -> dict:
    """노션의 글별 조회수(Views)를 도메인/카테고리별로 집계 — 수익 학습의 보상 신호."""
    client = core._notion()
    if client is None:
        return {}
    res = core._query_db(client, {"page_size": 100, "filter": {"property": "Views", "number": {"is_not_empty": True}}})
    agg: dict[str, dict] = {}
    top = []
    for p in res.get("results", []):
        pr = p["properties"]
        d = (pr["Domain"]["select"] or {}).get("name", "?")
        c = (pr.get("Category", {}).get("select") or {}).get("name", "")
        v = pr["Views"]["number"] or 0
        for key in (d, f"{d}/{c}"):
            a = agg.setdefault(key, {"posts": 0, "views": 0})
            a["posts"] += 1
            a["views"] += v
        top.append((v, "".join(t["plain_text"] for t in pr["Name"]["title"])[:50]))
    for a in agg.values():
        a["avg"] = round(a["views"] / a["posts"], 1)
    return {"by_group": agg, "top_posts": sorted(top, reverse=True)[:8]}


def learn_domain_weights(perf: dict, strategy: dict) -> dict[str, float]:
    """평균 조회수 기반 도메인 비중 (탐색을 위해 최소 15% 보장, 데이터 적으면 균등)."""
    by = perf.get("by_group", {})
    avgs = {d: by.get(d, {}).get("avg", 0.0) for d in core.DOMAINS}
    if sum(by.get(d, {}).get("posts", 0) for d in core.DOMAINS) < 8:  # 표본이 적으면 학습 보류
        return strategy.get("domain_weights") or {d: round(1 / len(core.DOMAINS), 3) for d in core.DOMAINS}
    total = sum(avgs.values()) or 1
    floor = 0.15
    raw = {d: floor + (1 - floor * len(avgs)) * avgs[d] / total for d in avgs}
    return {d: round(w, 3) for d, w in raw.items()}


def _due(strategy: dict, key: str, every: int) -> bool:
    last = strategy.get(key)
    if not last:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= every


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def feed_ok(url: str, min_entries: int = 3) -> bool:
    try:
        return len(core.fetch_feed(url).entries) >= min_entries
    except Exception:
        return False


# ─────────────────────────── [4]→[5] 전략 업데이트 ───────────────────────────
def update_strategy(strategy: dict) -> dict:
    mem = core.load_memory()
    changes: list[str] = []

    # 1) 결정적 규칙: 연속 0건 피드 차단
    for url, empty in mem.get("feed_health", {}).items():
        if empty >= BLOCK_AFTER_EMPTY and url not in strategy["blocked_feeds"]:
            strategy["blocked_feeds"].append(url)
            for d, urls in strategy["extra_feeds"].items():  # 자동 추가 피드 자리 반납
                strategy["extra_feeds"][d] = [u for u in urls if core.normalize_feed_url(u) != core.normalize_feed_url(url)]
            changes.append(f"피드 차단: {url}")

    # 2) 수익 보상 신호: 조회수 → 도메인 비중 학습 (GitHub Pages 방문수도 노션 Views 에 합산)
    try:
        import monetize
        pages = monetize.collect_pages()
        if pages:
            changes.append(f"Pages 30일 조회수 {pages['pv_30d']}")
    except Exception as e:
        log.warning("Pages 통계 수집 실패: %s", e)
    try:
        perf = performance_table()
    except Exception as e:
        log.warning("성과 집계 실패: %s", e)
        perf = {}
    weights = learn_domain_weights(perf, strategy)
    if weights != strategy.get("domain_weights"):
        strategy["domain_weights"] = weights
        changes.append(f"도메인 비중: {weights}")

    # 3) LLM 성찰 (Reflexion: 결과를 말로 반성 → 다음 실행 컨텍스트로 주입)
    runs = mem.get("runs", [])[-10:]
    counts = sorted(mem.get("category_counts", {}).items(), key=lambda kv: -kv[1])[:25]
    prompt = (
        f"You are the strategist of an automated Korean tech-news curation blog about: {core.domain_topics()}. "
        "The business goal is sustainable AdSense revenue (GitHub Pages site + Tistory; pageviews x RPM) while "
        "staying fully policy-compliant. Reflect on recent runs and performance, then improve the strategy.\n"
        f"Monetization playbook: {json.dumps(MONETIZATION_PLAYBOOK, ensure_ascii=False)}\n"
        f"Performance (Tistory views by domain/category, top posts): {json.dumps(perf, ensure_ascii=False)[:2500]}\n"
        f"Recent runs (stats/errors): {json.dumps(runs, ensure_ascii=False)[:3000]}\n"
        f"Category usage: {json.dumps(counts, ensure_ascii=False)}\n"
        f"Current editorial notes: {json.dumps(strategy['prompt_notes'], ensure_ascii=False)}\n"
        f"Current keyword hints: {json.dumps(strategy['keyword_hints'], ensure_ascii=False)}\n"
        f"Domains: {list(core.DOMAINS)}\n"
        "Return JSON with keys:\n"
        ' "lesson": one-sentence Korean lesson learned,\n'
        f' "prompt_notes": up to {MAX_NOTES} short editorial rules (Korean) that raise search traffic, reader value '
        'and AdSense quality (titles, depth, structure, category specificity) — learn from what got views, '
        'keep good existing ones,\n'
        ' "keyword_hints": {domain: up to 4 English topics with high search demand / commercial intent that '
        'match what performed well},\n'
        ' "feed_suggestions": up to 3 [{"domain": ..., "url": real RSS/Atom URL of a reputable source}]'
    )
    try:
        out = core._parse_json(core.llm(prompt, max_tokens=1200, json_mode=True))
    except Exception as e:  # LLM 실패해도 타임스탬프는 갱신 → 매 실행 재시도 폭주 방지
        log.warning("전략 성찰 LLM 실패: %s", e)
        out = {}
    out = out if isinstance(out, dict) else {}
    notes = [n.strip() for n in _as_list(out.get("prompt_notes")) if isinstance(n, str) and n.strip()][:MAX_NOTES]
    if notes and notes != strategy["prompt_notes"]:
        strategy["prompt_notes"] = notes
        changes.append(f"편집 가이드 {len(notes)}개 갱신")
    raw_hints = out.get("keyword_hints") if isinstance(out.get("keyword_hints"), dict) else {}
    hints = {d: [h for h in v if isinstance(h, str)][:4]  # 문자열이면 한 글자씩 쪼개지므로 리스트만 허용
             for d, v in raw_hints.items() if d in core.DOMAINS and isinstance(v, list)}
    if hints:
        strategy["keyword_hints"] = {**strategy["keyword_hints"], **hints}
        changes.append("검색 힌트 갱신: " + ", ".join(hints))

    # 4) 새 피드 후보는 실제로 파싱되는 것만 채택 (환각 URL 방지), URL 정규화로 중복 판별
    blocked = {core.normalize_feed_url(u) for u in strategy["blocked_feeds"]}
    for sug in _as_list(out.get("feed_suggestions"))[:3]:
        if not isinstance(sug, dict):
            continue
        d, url = sug.get("domain"), str(sug.get("url") or "").strip()
        known = {core.normalize_feed_url(u) for u in
                 core.DOMAINS.get(d, {}).get("feeds", []) + strategy["extra_feeds"].get(d, [])}
        n = core.normalize_feed_url(url) if url.startswith("http") else ""
        if d in core.DOMAINS and n and n not in known and n not in blocked \
                and len(strategy["extra_feeds"].get(d, [])) < MAX_EXTRA_FEEDS and feed_ok(url):
            strategy["extra_feeds"].setdefault(d, []).append(url)
            changes.append(f"피드 추가({d}): {url}")

    lesson = str(out.get("lesson") or "").strip()
    if lesson:
        mem = core.load_memory()
        mem["lessons"] = (mem.get("lessons", []) + [f"{datetime.now():%Y-%m-%d} [성찰] {lesson}"])[-20:]
        core._save_json(core.MEMORY_PATH, mem)
    strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "lesson": lesson, "changes": changes}])[-30:]
    strategy["strategy_updated_at"] = _now()
    log.info("전략 업데이트: %s", changes or "변경 없음")
    return strategy


# ─────────────────────────── 카테고리 체계 정제 (TNT-LLM refine) ───────────────────────────
def apply_merge(domain: str, src: str, dst: str, notion=None) -> int:
    """src 카테고리를 dst 로 병합: memory 목록·사용 횟수 + 노션 페이지 Category 갱신."""
    mem = core.load_memory()
    cats = mem.setdefault("categories", {}).setdefault(domain, [])
    if src in cats:
        cats.remove(src)
    if dst not in cats and dst not in core.SEED_CATEGORIES.get(domain, []):
        cats.append(dst)
    merged = mem.setdefault("category_merges", {})  # 시드 카테고리도 병합되면 이후 선택지에서 제외
    merged.pop(f"{domain}/{dst}", None)  # dst 가 예전에 병합돼 숨겨졌다면 되살림 (A→B 후 B→A 순환 방지)
    merged[f"{domain}/{src}"] = dst
    for k, v in list(merged.items()):  # 체인 정리: X→src 였던 것은 X→dst
        if k.startswith(f"{domain}/") and v == src:
            merged[k] = dst
    counts = mem.setdefault("category_counts", {})
    counts[f"{domain}/{dst}"] = counts.get(f"{domain}/{dst}", 0) + counts.pop(f"{domain}/{src}", 0)
    core._save_json(core.MEMORY_PATH, mem)
    updated = 0
    if notion is not None:
        flt = {"and": [{"property": "Domain", "select": {"equals": domain}},
                       {"property": "Category", "select": {"equals": src}}]}
        while True:  # 갱신된 페이지는 필터에서 빠지므로 결과가 없을 때까지 반복 (페이지네이션)
            res = core._query_db(notion, {"page_size": 50, "filter": flt})
            for p in res.get("results", []):
                notion.pages.update(page_id=p["id"], properties={"Category": {"select": {"name": dst}}})
                updated += 1
                time.sleep(0.4)  # 노션 3 req/s 제한
            if not res.get("results") or updated >= 500:
                break
    return updated


def refine_taxonomy(strategy: dict) -> dict:
    cats = core.load_categories()
    counts = core.load_memory().get("category_counts", {})
    table = {d: {c: counts.get(f"{d}/{c}", 0) for c in cs} for d, cs in cats.items()}
    prompt = (
        f"You maintain a 2-level taxonomy (domain > specific sub-category) for a Korean blog about: {core.domain_topics()}.\n"
        f"Current sub-categories with post counts: {json.dumps(table, ensure_ascii=False)}\n"
        "1) Merge only true duplicates or near-synonyms (e.g. '렌더링' vs '렌더링 기술'). Keep specific categories "
        "(tool/technique level) — do NOT collapse specific ones into broad ones. Never merge across domains.\n"
        "2) For broad or overloaded categories (e.g. '제작 사례', '툴 업데이트'), propose 2-4 more specific "
        "sub-categories (tool/technique/product level) to use for future posts.\n"
        'Return JSON {"merges": [{"domain": ..., "from": existing name, "to": existing or better Korean name}], '
        '"splits": [{"domain": ..., "from": broad name, "into": ["specific Korean name", ...]}]} '
        "(max 8 merges, max 4 splits; empty lists if nothing to do)."
    )
    try:
        out = core._parse_json(core.llm(prompt, max_tokens=800, json_mode=True))
    except Exception as e:
        log.warning("카테고리 정제 LLM 실패: %s", e)
        out = {}
    out = out if isinstance(out, dict) else {}
    notion = core._notion()
    done = []
    for m in _as_list(out.get("merges"))[:8]:
        if not isinstance(m, dict):
            continue
        d, src, dst = m.get("domain"), str(m.get("from") or "").strip(), str(m.get("to") or "").strip()[:24]
        if d in cats and src in cats[d] and dst and dst != src:
            n = apply_merge(d, src, dst, notion)
            done.append(f"{d}: {src} → {dst} (노션 {n}건)")
    for sp in _as_list(out.get("splits"))[:4]:  # 넓은 카테고리 → 구체적 하위 선택지 추가 (기존 글은 그대로)
        if not isinstance(sp, dict):
            continue
        d = sp.get("domain")
        if d in cats and sp.get("from") in cats[d]:
            added = [core.register_new_option(d, n) for n in _as_list(sp.get("into"))[:4] if isinstance(n, str)]
            if any(added):
                done.append(f"{d}: {sp['from']} ⇒ {', '.join(a for a in added if a)}")
    strategy["taxonomy_updated_at"] = _now()
    strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "taxonomy_merges": done}])[-30:]
    log.info("카테고리 정제: %s", done or "병합 없음")
    return strategy


def evolve(stats: dict | None = None, force: bool = False) -> dict:
    strategy = core.load_strategy()
    for key in ("prompt_notes", "blocked_feeds", "history"):
        strategy.setdefault(key, [])
    for key in ("keyword_hints", "extra_feeds"):
        strategy.setdefault(key, {})
    if force or _due(strategy, "strategy_updated_at", STRATEGY_EVERY):
        strategy = update_strategy(strategy)
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "taxonomy_updated_at", TAXONOMY_EVERY):
        strategy = refine_taxonomy(strategy)
        core._save_json(core.STRATEGY_PATH, strategy)
    return strategy


if __name__ == "__main__":
    print(json.dumps(evolve(force=True), ensure_ascii=False, indent=2))
