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


def _due(strategy: dict, key: str, every: int) -> bool:
    last = strategy.get(key)
    if not last:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= every


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def feed_ok(url: str, min_entries: int = 3) -> bool:
    try:
        d = feedparser.parse(url, request_headers=core.HTTP_HEADERS)
        return len(d.entries) >= min_entries
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
            changes.append(f"피드 차단: {url}")

    # 2) LLM 성찰 (Reflexion: 결과를 말로 반성 → 다음 실행 컨텍스트로 주입)
    runs = mem.get("runs", [])[-10:]
    counts = sorted(mem.get("category_counts", {}).items(), key=lambda kv: -kv[1])[:25]
    prompt = (
        "You are the strategist of an automated Korean tech-news curation blog about 3D DCC, game engines, "
        "VFX and AI 3D. Reflect on recent runs and improve the strategy.\n"
        f"Recent runs (stats/errors): {json.dumps(runs, ensure_ascii=False)[:3500]}\n"
        f"Category usage: {json.dumps(counts, ensure_ascii=False)}\n"
        f"Current editorial notes: {json.dumps(strategy['prompt_notes'], ensure_ascii=False)}\n"
        f"Current keyword hints: {json.dumps(strategy['keyword_hints'], ensure_ascii=False)}\n"
        f"Domains: {list(core.DOMAINS)}\n"
        "Return JSON with keys:\n"
        ' "lesson": one-sentence Korean lesson learned,\n'
        f' "prompt_notes": up to {MAX_NOTES} short editorial rules (Korean) to improve summaries for Korean '
        'readers, AdSense quality and category specificity (keep good existing ones),\n'
        ' "keyword_hints": {domain: up to 4 English topics that are trending or under-covered},\n'
        ' "feed_suggestions": up to 3 [{"domain": ..., "url": real RSS/Atom URL of a reputable source}]'
    )
    out = core._parse_json(core.llm(prompt, max_tokens=1200, json_mode=True))
    notes = [n.strip() for n in out.get("prompt_notes", []) if isinstance(n, str) and n.strip()][:MAX_NOTES]
    if notes and notes != strategy["prompt_notes"]:
        strategy["prompt_notes"] = notes
        changes.append(f"편집 가이드 {len(notes)}개 갱신")
    hints = {d: [h for h in v if isinstance(h, str)][:4]
             for d, v in (out.get("keyword_hints") or {}).items() if d in core.DOMAINS}
    if hints:
        strategy["keyword_hints"] = {**strategy["keyword_hints"], **hints}
        changes.append("검색 힌트 갱신: " + ", ".join(hints))

    # 3) 새 피드 후보는 실제로 파싱되는 것만 채택 (환각 URL 방지)
    for sug in out.get("feed_suggestions", [])[:3]:
        d, url = sug.get("domain"), (sug.get("url") or "").strip()
        known = set(core.DOMAINS.get(d, {}).get("feeds", [])) | set(strategy["extra_feeds"].get(d, []))
        if d in core.DOMAINS and url.startswith("http") and url not in known \
                and url not in strategy["blocked_feeds"] \
                and len(strategy["extra_feeds"].get(d, [])) < MAX_EXTRA_FEEDS and feed_ok(url):
            strategy["extra_feeds"].setdefault(d, []).append(url)
            changes.append(f"피드 추가({d}): {url}")

    lesson = (out.get("lesson") or "").strip()
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
    merged[f"{domain}/{src}"] = dst
    counts = mem.setdefault("category_counts", {})
    counts[f"{domain}/{dst}"] = counts.get(f"{domain}/{dst}", 0) + counts.pop(f"{domain}/{src}", 0)
    core._save_json(core.MEMORY_PATH, mem)
    updated = 0
    if notion is not None:
        res = core._query_db(notion, {"page_size": 50, "filter": {"and": [
            {"property": "Domain", "select": {"equals": domain}},
            {"property": "Category", "select": {"equals": src}}]}})
        for p in res.get("results", []):
            notion.pages.update(page_id=p["id"], properties={"Category": {"select": {"name": dst}}})
            updated += 1
            time.sleep(0.4)  # 노션 3 req/s 제한
    return updated


def refine_taxonomy(strategy: dict) -> dict:
    cats = core.load_categories()
    counts = core.load_memory().get("category_counts", {})
    table = {d: {c: counts.get(f"{d}/{c}", 0) for c in cs} for d, cs in cats.items()}
    prompt = (
        "You maintain a 2-level taxonomy (domain > specific sub-category) for a Korean 3D/VFX/game/AI-3D blog.\n"
        f"Current sub-categories with post counts: {json.dumps(table, ensure_ascii=False)}\n"
        "1) Merge only true duplicates or near-synonyms (e.g. '렌더링' vs '렌더링 기술'). Keep specific categories "
        "(tool/technique level) — do NOT collapse specific ones into broad ones. Never merge across domains.\n"
        "2) For broad or overloaded categories (e.g. '제작 사례', '툴 업데이트'), propose 2-4 more specific "
        "sub-categories (tool/technique/product level) to use for future posts.\n"
        'Return JSON {"merges": [{"domain": ..., "from": existing name, "to": existing or better Korean name}], '
        '"splits": [{"domain": ..., "from": broad name, "into": ["specific Korean name", ...]}]} '
        "(max 8 merges, max 4 splits; empty lists if nothing to do)."
    )
    out = core._parse_json(core.llm(prompt, max_tokens=800, json_mode=True))
    notion = core._notion()
    done = []
    for m in out.get("merges", [])[:8]:
        d, src, dst = m.get("domain"), (m.get("from") or "").strip(), (m.get("to") or "").strip()[:24]
        if d in cats and src in cats[d] and dst and dst != src:
            n = apply_merge(d, src, dst, notion)
            done.append(f"{d}: {src} → {dst} (노션 {n}건)")
    for sp in out.get("splits", [])[:4]:  # 넓은 카테고리 → 구체적 하위 선택지 추가 (기존 글은 그대로)
        d = sp.get("domain")
        if d in cats and sp.get("from") in cats[d]:
            added = [core.register_new_option(d, n) for n in sp.get("into", [])[:4] if isinstance(n, str)]
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
