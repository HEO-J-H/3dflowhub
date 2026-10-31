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
import re
import time
import hashlib
from datetime import datetime, timedelta, timezone


import core
import growth

log = core.log
STRATEGY_EVERY = 6 * 3600      # 데이터가 적어도 최소 이 주기로는 성찰
STRATEGY_MIN_GAP = 3600        # 데이터가 충분하면 최대 1시간마다 (10분마다는 평가 표본 부족·LLM 낭비)
MIN_ITEMS_PER_VERSION = 15     # 가이드 한 버전을 평가하려면 최소 이만큼의 수집 글
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


def site_performance_table() -> dict:
    """노션 미사용 시 보상 신호: GitHub Pages 방문수(GoatCounter) + 티스토리 조회수를 content/posts 분류로 집계."""
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
    pages = (perf.get("pages") or {}).get("posts", {})
    tistory = {v.get("title"): v.get("views", 0) for v in ((perf.get("latest") or {}).get("posts") or {}).values()}
    agg: dict[str, dict] = {}
    top = []
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        v = pages.get(f.stem, {}).get("views", 0) + tistory.get(p.get("title_ko"), 0)
        if not v:
            continue
        d, c = p.get("domain", "?"), p.get("category", "")
        for key in (d, f"{d}/{c}"):
            a = agg.setdefault(key, {"posts": 0, "views": 0})
            a["posts"] += 1
            a["views"] += v
        top.append((v, (p.get("title_ko") or "")[:50]))
    for a in agg.values():
        a["avg"] = round(a["views"] / a["posts"], 1)
    return {"by_group": agg, "top_posts": sorted(top, reverse=True)[:8]}


def performance_table() -> dict:
    """노션의 글별 조회수(Views)를 도메인/카테고리별로 집계 및 상위 글 제목 길이 평균 집계 반환 — 수익 학습의 보상 신호."""
    client = core._notion()
    perf_data = site_performance_table() if client is None else None

    if client is None:
        agg = perf_data["by_group"]
        top = perf_data["top_posts"]
    else:
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
        top = sorted(top, reverse=True)[:8]

    title_stats = {"avg_length": 0.0, "count": len(top)}
    if top:
        total_len = sum(len(title) for _, title in top)
        title_stats["avg_length"] = round(total_len / len(top), 1)

    return {"by_group": agg, "top_posts": top, "title_stats": title_stats}


def learn_tool_interest(top_n: int = 4, prior_views: float = 1.0, prior_posts: float = 3.0,
                        min_total_views: int = 20) -> dict[str, list[str]]:
    """도구별 독자 관심도: 사이트 글별 조회수(GoatCounter) + 에디터 추천(+3)을 도구 단위로 모아
    베이지안 평균(작은 표본 과대평가 방지)으로 분야별 상위 도구를 고른다. 조회수가 적으면 학습 보류({})."""
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
    views = {k: v.get("views", 0) for k, v in ((perf.get("pages") or {}).get("posts") or {}).items()}
    if sum(views.values()) < min_total_views:
        return {}
    cur = core.curation_state()
    agg: dict[tuple, list] = {}
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        tool = p.get("category") or ""
        if not tool or tool.startswith("기타") or cur.get(f.stem) == "hide":
            continue
        a = agg.setdefault((p.get("domain"), tool), [0.0, 0])
        a[0] += views.get(f.stem, 0) + (3 if cur.get(f.stem) == "pick" else 0)
        a[1] += 1
    prior = prior_views / prior_posts
    score = {k: (v + prior * prior_posts) / (n + prior_posts) for k, (v, n) in agg.items()}
    out: dict[str, list[str]] = {}
    for (d, tool), sc in sorted(score.items(), key=lambda kv: -kv[1]):
        if sc > prior and len(out.setdefault(d, [])) < top_n:
            out[d].append(tool)
    return {d: v for d, v in out.items() if v}


def learn_domain_weights(perf: dict, strategy: dict) -> dict[str, float]:
    """평균 조회수 기반 도메인 비중 (탐색을 위해 최소 15% 보장, 데이터 적으면 균등)."""
    by = perf.get("by_group", {})
    avgs = {d: by.get(d, {}).get("avg", 0.0) for d in core.DOMAINS}
    if sum(by.get(d, {}).get("posts", 0) for d in core.DOMAINS) < 8:  # 표본이 적으면 학습 보류
        return strategy.get("domain_weights") or {d: round(1 / len(core.DOMAINS), 3) for d in core.DOMAINS}
    total = sum(avgs.values()) or 1
    floor = min(0.15, 0.5 / len(avgs))  # 분야가 많아도 음수·역전 없음 (최소 비중 합 ≤ 50%)
    raw = {d: floor + (1 - floor * len(avgs)) * avgs[d] / total for d in avgs}
    s_ = sum(raw.values()) or 1
    return {d: round(w / s_, 3) for d, w in raw.items()}


def _due(strategy: dict, key: str, every: int) -> bool:
    last = strategy.get(key)
    if not last:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= every


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


MIN_RUNS_PER_VERSION = 3  # 가이드 한 묶음을 최소 이만큼 실행해 본 뒤 교체 (잦은 교체로 평가 불가 방지)


def analyze_run_errors() -> dict[str, float]:
    """최근 실행 오류(RUN_ERRORS 및 runs 기록)에서 'short post' 및 'off-topic' 비율을 집계하여 통계 반환."""
    runs = core.load_memory().get("runs", [])
    total_runs = len(runs)
    if total_runs == 0:
        return {"short_post_rate": 0.0, "off_topic_rate": 0.0, "total_runs": 0}

    total_short = sum(int(r.get("short", 0) or 0) for r in runs)
    total_offtopic = sum(int(r.get("offtopic", 0) or 0) for r in runs)
    total_collected = sum(int(r.get("collected", 0) or 0) for r in runs) or 1

    return {
        "short_post_rate": round(total_short / total_collected, 4),
        "off_topic_rate": round(total_offtopic / total_collected, 4),
        "total_runs": total_runs,
    }


def score_trajectory(runs: list[dict], versions: dict) -> list[dict]:
    """OPRO 식 궤적: 가이드 버전별 실행 결과를 점수화해 오름차순 반환 (Yang et al., 2023)."""
    agg: dict[str, dict] = {}
    for r in runs:
        v = r.get("strategy_ver")
        if not v:
            continue
        a = agg.setdefault(v, {"runs": 0, "collected": 0, "saved": 0, "offtopic": 0, "short": 0})
        a["runs"] += 1
        for k in ("collected", "saved", "offtopic", "short"):
            a[k] += int(r.get(k, 0) or 0)
    out = []
    for v, a in agg.items():
        c = a["collected"] or 1
        out.append({"ver": v, "notes": versions.get(v, [])[:6], "runs": a["runs"], "collected": a["collected"],
                    "pass_rate": round(a["saved"] / c, 2), "offtopic_rate": round(a["offtopic"] / c, 2),
                    "score": round((a["saved"] - 0.5 * a["offtopic"] - 0.5 * a["short"]) / c, 3)})
    return sorted(out, key=lambda t: t["score"])


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
    collect_pages_due(strategy)  # 보통은 evolve() 가 이미 수집함 — 성찰 직전에 한 번 더 확인
    try:
        perf = performance_table()
    except Exception as e:
        log.warning("성과 집계 실패: %s", e)
        perf = {}
    interest = learn_tool_interest()
    if interest and interest != strategy.get("tool_interest"):
        strategy["tool_interest"] = interest
        changes.append(f"독자 관심 도구: {interest}")
    weights = learn_domain_weights(perf, strategy)
    if weights != strategy.get("domain_weights"):
        strategy["domain_weights"] = weights
        changes.append(f"도메인 비중: {weights}")

    # 3) LLM 성찰 (Reflexion: 결과를 말로 반성) + OPRO: 과거 가이드 묶음과 점수 궤적을 함께 보여줌
    runs = mem.get("runs", [])[-10:]
    cur_ver = core.strategy_version(strategy["prompt_notes"])
    versions = strategy.setdefault("note_versions", {})
    versions.setdefault(cur_ver, strategy["prompt_notes"])
    trajectory = score_trajectory(mem.get("runs", []), versions)
    cur = next((t for t in trajectory if t["ver"] == cur_ver), {"runs": 0})
    enough = cur["runs"] >= MIN_RUNS_PER_VERSION or not strategy["prompt_notes"]
    counts = sorted(mem.get("category_counts", {}).items(), key=lambda kv: -kv[1])[:25]
    prompt = (
        f"You are the strategist of an automated Korean tech-news curation blog about: {core.domain_topics()}. "
        "The business goal is sustainable AdSense revenue (GitHub Pages site + Tistory; pageviews x RPM) while "
        "staying fully policy-compliant. Reflect on recent runs and performance, then improve the strategy.\n"
        f"Monetization playbook: {json.dumps(MONETIZATION_PLAYBOOK, ensure_ascii=False)}\n"
        f"Performance (Tistory views by domain/category, top posts): {json.dumps(perf, ensure_ascii=False)[:2500]}\n"
        f"Recent runs (stats/errors): {json.dumps(runs, ensure_ascii=False)[:3000]}\n"
        f"Category usage: {json.dumps(counts, ensure_ascii=False)}\n"
        f"Reader interest by tool (most-viewed per site analytics): "
        f"{json.dumps(strategy.get('tool_interest', {}), ensure_ascii=False)}\n"
        f"Google search queries that already show this site (impressions; write more for these): "
        f"{json.dumps(_gsc_hint(), ensure_ascii=False)[:1200]}\n"
        f"Human editor feedback (strongest signal: collect more like PICKED, avoid what was HIDDEN): "
        f"{json.dumps(editor_feedback(), ensure_ascii=False)[:1500]}\n"
        f"Current editorial notes: {json.dumps(strategy['prompt_notes'], ensure_ascii=False)}\n"
        "Previous editorial-note sets with measured scores (ascending; score = good posts per collected "
        "article minus off-topic/short penalties). Write notes that should beat the best set:\n"
        f"{json.dumps(trajectory[-6:], ensure_ascii=False)[:2500]}\n"
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
    rolled = growth.rollback_if_worse(strategy, trajectory)  # 확실히 나빠진 지침은 최고 버전으로 되돌림
    if rolled:
        changes.append(rolled)
    elif notes and notes != strategy["prompt_notes"] and enough:  # 현재 가이드 평가 데이터가 쌓였을 때만 교체
        if growth.set_notes(strategy, notes, f"성찰 갱신 (이전 {cur_ver}: {cur['runs']}회, 점수 {cur.get('score', '-')})"):
            notes = strategy["prompt_notes"]
            versions[core.strategy_version(notes)] = notes
            strategy["note_versions"] = dict(list(versions.items())[-12:])
            changes.append(f"편집 가이드 {len(notes)}개 갱신 (이전 {cur_ver}: {cur['runs']}회, 점수 {cur.get('score', '-')})")
    elif notes and not enough:
        changes.append(f"편집 가이드 유지 — 현재 버전 평가 중 ({cur['runs']}/{MIN_RUNS_PER_VERSION}회)")
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
        f"You maintain the TOOL/PRODUCT level of a 3-level taxonomy (domain > tool/product > content type) for a "
        f"Korean blog about: {core.domain_topics()}.\n"
        f"Current tools/products per domain with post counts: {json.dumps(table, ensure_ascii=False)}\n"
        f"Content types are fixed and separate: {core.TOPICS} — they must NOT appear as tools.\n"
        "1) Merge true duplicates/aliases of the same product (e.g. 'UE5' → 'Unreal Engine', 'Blender 업데이트' → 'Blender', "
        "'툴 업데이트' or '튜토리얼' are content types → merge into the domain's '기타 …' or the right tool). "
        "Never merge different products. Never merge across domains.\n"
        "2) If a '기타 …' bucket is large and several posts share one product, propose that product as a new tool "
        "(splits).\n"
        'Return JSON {"merges": [{"domain": ..., "from": existing name, "to": existing or official product name}], '
        '"splits": [{"domain": ..., "from": broad name, "into": ["official product name", ...]}]} '
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
        d, src = m.get("domain"), str(m.get("from") or "").strip()
        dst = re.sub(r"[/|<>,]", "·", str(m.get("to") or "").strip())[:24]
        if dst in core.TOPICS:  # 콘텐츠 유형은 도구가 될 수 없음
            continue
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


TERM_AUDIT_EVERY = 24 * 3600
TERM_STOPWORDS = {"구글", "애플", "엔비디아", "어도비", "마이크로소프트", "유튜브", "디스코드", "안드로이드", "리눅스",
                  "아이패드", "스타일라이즈드", "그래픽카드", "테크놀로지", "파운데이션", "게임즈", "스파이더맨",
                  "사이버펑크", "포트나이트", "스타워즈", "텔레콤"}


def calculate_cpc_score_distribution() -> dict:
    """최근 발행된 콘텐츠의 도메인별·키워드별 고CPC 잠재력을 수치화하여 분석하고 전략 리포트에 반영하는 통계 함수."""
    posts_dir = core.POSTS_DIR
    if not posts_dir.exists():
        return {"by_domain": {}, "high_cpc_keywords": [], "total_analyzed": 0}

    # 고CPC 연관 핵심 키워드 가중치 사전 (소프트웨어 툴, 하드웨어, 렌더러, 플러그인 등)
    high_cpc_keywords_weights = {
        "v-ray": 1.5, "corona": 1.5, "unreal engine": 1.4, "unity": 1.3,
        "substance": 1.3, "houdini": 1.4, "zbrush": 1.3, "3ds max": 1.4,
        "maya": 1.4, "blender": 1.2, "gpu": 1.5, "rtx": 1.5, "plugin": 1.3,
        "script": 1.3, "tutorial": 1.4, "workflow": 1.3, "render": 1.3
    }

    by_domain: dict[str, dict] = {}
    keyword_scores: dict[str, float] = {}
    total_analyzed = 0

    for f in posts_dir.glob("*.json"):
        p = core._load_json(f, {})
        domain = p.get("domain", "기타")
        title = p.get("title_ko", "") or p.get("title", "")
        summary = p.get("summary", "")
        tags = p.get("tags", [])
        sections_text = " ".join(s.get("heading", "") + " " + s.get("body", "") for s in p.get("sections", []))
        
        full_text = f"{title} {summary} {' '.join(tags)} {sections_text}".lower()
        total_analyzed += 1

        # 도메인별 통계 집계 초기화
        if domain not in by_domain:
            by_domain[domain] = {"post_count": 0, "cumulative_cpc_score": 0.0, "avg_cpc_score": 0.0}
        
        domain_score = 1.0
        for kw, weight in high_cpc_keywords_weights.items():
            if kw in full_text:
                domain_score *= weight
                keyword_scores[kw] = keyword_scores.get(kw, 0.0) + weight

        by_domain[domain]["post_count"] += 1
        by_domain[domain]["cumulative_cpc_score"] += domain_score

    # 평균 고CPC 잠재력 수치 계산
    for d, stats in by_domain.items():
        cnt = stats["post_count"]
        if cnt > 0:
            stats["avg_cpc_score"] = round(stats["cumulative_cpc_score"] / cnt, 2)

    # 상위 고CPC 키워드 정렬 추출
    sorted_keywords = sorted(keyword_scores.items(), key=lambda x: -x[1])
    top_keywords = [{"keyword": kw, "score": round(score, 2)} for kw, score in sorted_keywords[:10]]

    report = {
        "by_domain": by_domain,
        "high_cpc_keywords": top_keywords,
        "total_analyzed": total_analyzed
    }
    
    # 전략 리포트(strategy.json) 또는 전략 메모리에 고CPC 분석 결과 반영
    try:
        strat = core.load_strategy()
        strat["cpc_score_distribution"] = report
        core._save_json(core.STRATEGY_PATH, strat)
    except Exception as e:
        log.warning("전략 리포트에 CPC 분석 결과 반영 실패: %s", e)

    return report


def summarize_error_trends() -> dict[str, dict[str, int]]:
    """최근 실행 오류(RUN_ERRORS) 및 runs 기록의 오류 유형들을 도메인별·유형별로 집계하여 리포트 형태로 반환."""
    runs = core.load_memory().get("runs", [])
    domain_type_counts: dict[str, dict[str, int]] = {}
    
    for r in runs:
        errors = r.get("errors", [])
        # runs 기록 내 통계 필드(short, offtopic 등)도 에러 유형으로 간주하여 집계
        if int(r.get("short", 0) or 0) > 0:
            errors.append("short body")
        if int(r.get("offtopic", 0) or 0) > 0:
            errors.append("off-topic")
            
        domain = r.get("domain", "전체")
        if not domain or not isinstance(domain, str):
            domain = "전체"
            
        if domain not in domain_type_counts:
            domain_type_counts[domain] = {}
            
        for err in errors:
            if not err or not isinstance(err, str):
                continue
            err_key = err.strip()
            # 오류 메시지에서 주요 유형 추출 (예: 'short body', 'off-topic', 'prefiltered', 또는 429 등)
            if "429" in err_key or "한도" in err_key:
                err_type = "AI 한도 소진 (429)"
            elif "short body" in err_key or "short post" in err_key:
                err_type = "본문 길이 미달"
            elif "off-topic" in err_key or "prefiltered" in err_key:
                err_type = "주제 무관/필터링됨"
            elif "json" in err_key.lower() or "sections" in err_key:
                err_type = "JSON/형식 오류"
            else:
                err_type = "기타 오류"
                
            domain_type_counts[domain][err_type] = domain_type_counts[domain].get(err_type, 0) + 1

    return domain_type_counts


def analyze_3d_content_distribution() -> dict[str, float]:
    """최근 생성된 콘텐츠의 도메인별(3D DCC, Game Engine, VFX, AI 3D) 분포 비율을 집계하여 리포트 형태로 반환."""
    dist: dict[str, int] = {"3D DCC": 0, "Game Engine": 0, "VFX": 0, "AI 3D": 0}
    total = 0
    if core.POSTS_DIR.exists():
        for f in core.POSTS_DIR.glob("*.json"):
            p = core._load_json(f, {})
            d = p.get("domain")
            if d in dist:
                dist[d] += 1
                total += 1
    percentages = {}
    for k, v in dist.items():
        percentages[k] = round((v / total) * 100, 2) if total > 0 else 0.0
    return {"counts": dist, "total": total, "percentages": percentages}


def audit_terms(max_words: int = 1500, batch: int = 500) -> dict[str, str]:
    """용어 자가 학습: 글에 자주 나오는 한글 단어 중 '음역된 고유명사(소프트웨어·플러그인·회사·기술명)'를 찾아
    정식 영문 표기를 memory['glossary_learned'] 에 추가 → core.fix_terms 가 이후 자동 교정."""
    import collections
    import re as _re
    counts = collections.Counter()
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        text = " ".join([p.get("title_ko", ""), p.get("summary", ""), *(p.get("tags") or [])] +
                        [f'{s.get("heading", "")} {s.get("body", "")}' for s in p.get("sections") or []])
        for w in _re.findall(r"[가-힣]{2,10}", text):
            counts[_re.sub(r"(은|는|이|가|을|를|의|에|와|과|로|으로|에서|도|만)$", "", w)] += 1
    known = {k for k in core.GLOSSARY} | set(core.load_memory().get("glossary_learned", {}).values())
    words = [w for w, _ in counts.most_common(max_words)]
    found: dict[str, str] = {}
    for i in range(0, len(words), batch):
        chunk = words[i:i + batch]
        prompt = ("Below are Korean words from a Korean 3D/CG/game-engine/VFX/AI news site. Return ONLY complete words "
                  "that are Hangul transliterations of TECHNICAL product names a Korean CG artist would normally write in "
                  "English: software, plugins, scripting languages, APIs/SDKs, file formats, engine features "
                  "(e.g. 맥로스크립트→MacroScript, 레일클론→RailClone, 나나이트→Nanite, 메타휴먼→MetaHuman). "
                  "EXCLUDE: companies/brands (구글, 애플, 엔비디아, 어도비), games/films/people, words Koreans normally "
                  "write in Hangul (유튜브, 디스코드, 파이썬 is fine to include), generic loanwords (모델링, 렌더링, "
                  "텍스처, 플러그인, 스타일라이즈드, 그래픽카드), and FRAGMENTS of longer names (스타, 워즈, 휴먼, 게임즈, 맥스).\n"
                  f"Words: {', '.join(chunk)}\n"
                  'Return JSON {"terms": {"hangul": "Official English", ...}} (empty if none).')
        try:
            out = core._parse_json(core.llm(prompt, max_tokens=1500, json_mode=True))
        except Exception as e:
            log.warning("용어 점검 실패: %s", e)
            continue
        for k, v in (out.get("terms") or {}).items():
            if (isinstance(k, str) and isinstance(v, str) and _re.fullmatch(r"[가-힣]{3,12}", k)
                    and k not in TERM_STOPWORDS
                    and _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .+\-]{1,30}", v) and v not in known):
                found[k] = v.strip()
    if found:
        mem = core.load_memory()
        mem["glossary_learned"] = {**mem.get("glossary_learned", {}), **found}
        core._save_json(core.MEMORY_PATH, mem)
    return found


def strategy_due(strategy: dict) -> bool:
    """적응형 주기: 6시간이 지났거나, 1시간이 지났고 현재 가이드 버전의 평가 표본이 충분할 때."""
    if _due(strategy, "strategy_updated_at", STRATEGY_EVERY):
        return True
    if not _due(strategy, "strategy_updated_at", STRATEGY_MIN_GAP):
        return False
    ver = core.strategy_version(strategy.get("prompt_notes", []))
    cur = next((t for t in score_trajectory(core.load_memory().get("runs", []), {}) if t["ver"] == ver), None)
    return bool(cur and cur["runs"] >= MIN_RUNS_PER_VERSION and cur["collected"] >= MIN_ITEMS_PER_VERSION)


def _gsc_hint() -> dict:
    try:
        import gsc
        return {"top": gsc.top_queries(15), "low_ctr_opportunities": [r["key"] for r in gsc.opportunities(8)]}
    except Exception:
        return {}


def editor_feedback(n: int = 15) -> dict:
    """대시보드에서 사람이 추천/숨김한 글 제목·도구 (성찰 프롬프트용)."""
    out: dict[str, list] = {"picked": [], "hidden": []}
    reasons = core.curation_reasons()
    for pid, v in list(core.curation_state().items())[-200:]:
        post = core._load_json(core.POSTS_DIR / f"{pid}.json", {})
        if post.get("title_ko"):
            why = reasons.get(pid, "")
            out["picked" if v == "pick" else "hidden"].append(
                f"[{post.get('domain')}/{post.get('category')}] {post['title_ko']}" + (f" (사유: {why})" if why else ""))
    return {k: v[-n:] for k, v in out.items()}


ROUNDUP_EVERY = timedelta(days=7)
ROUNDUP_MIN_POSTS = 4


def roundup_path(domain: str, tool: str):
    return core.ROUNDUP_DIR / f"{hashlib.md5(f'{domain}|{tool}'.encode()).hexdigest()[:12]}.json"


def write_roundups(max_new: int = 3, days: int = 30, gate: bool = True) -> list[str]:
    """도구별 정리: 최근 30일 글이 4개 이상인 도구를 주 1회 LLM 으로 묶어 '흐름·핵심·먼저 볼 글' 정리.
    개별 요약보다 검색·독자 가치가 큰 2차 콘텐츠. 한도의 60% 이상 남았을 때만, 한 번에 최대 3개."""
    budget = int(core.load_config().get("llm_daily_budget", 500))
    if max_new <= 0 or (gate and core.llm_budget_left() < budget * 0.6):
        return []
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    hidden = {k for k, v in core.curation_state().items() if v == "hide"}
    groups: dict[tuple, list] = {}
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        if (p.get("title_ko") and (p.get("collected_at") or "") >= cutoff and f.stem not in hidden
                and p.get("category") and not str(p["category"]).startswith("기타")):
            groups.setdefault((p.get("domain"), p["category"]), []).append({**p, "id": f.stem})
    done: list[str] = []
    for (domain, tool), ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(done) >= max_new:
            break
        path = roundup_path(domain, tool)
        if len(ps) < ROUNDUP_MIN_POSTS or core._load_json(path, {}).get("at", "") >= (now - ROUNDUP_EVERY).isoformat():
            continue
        ps.sort(key=lambda p: p.get("collected_at") or "", reverse=True)
        items = [{"id": p["id"], "title": p["title_ko"], "type": p.get("topic", ""),
                  "summary": (p.get("summary") or "")[:220]} for p in ps[:15]]
        prompt = (
            f"Tool: {tool} (field: {domain}). Below are {len(items)} recent Korean article summaries about it.\n"
            f"{json.dumps(items, ensure_ascii=False)}\n"
            "Write a Korean roundup page for learners and practitioners. Use only facts in the summaries; "
            "keep official English product names (e.g. MAXScript, Geometry Nodes). Return JSON:\n"
            ' "title": Korean page title (<=40 chars, e.g. "Blender 최근 한 달 핵심 정리"),\n'
            ' "intro": 3-4 sentences on the overall trend this month,\n'
            ' "points": 3-5 key takeaways (one concrete sentence each),\n'
            ' "picks": up to 5 ids most worth reading first, "why": {id: one short Korean reason}'
        )
        try:
            out = core._parse_json(core.llm(prompt, system="You are the editor of 3dflowhub." + core.playbook("common", "editor"),
                                             max_tokens=1200, json_mode=True))
        except core.LLMBudgetExceeded:
            break
        except Exception as e:
            log.warning("도구별 정리 실패 %s/%s: %s", domain, tool, e)
            continue
        if not isinstance(out, dict) or not out.get("intro"):
            continue
        valid = {p["id"] for p in ps}
        core._save_json(path, {
            "at": now.isoformat(), "domain": domain, "tool": tool,
            "title": core.fix_terms(str(out.get("title") or f"{tool} 최근 핵심 정리"))[:60],
            "intro": core.fix_terms(str(out["intro"])),
            "points": [core.fix_terms(str(x)) for x in (out.get("points") or [])][:5],
            "picks": [i for i in (out.get("picks") or []) if i in valid][:5],
            "why": {k: core.fix_terms(str(v)) for k, v in (out.get("why") or {}).items() if k in valid},
            "post_ids": [p["id"] for p in ps]})
        done.append(f"{domain}/{tool}")
    return done


def collect_pages_due(strategy: dict) -> bool:
    """방문 통계(GoatCounter) 3시간마다 수집. 성찰 주기(최대 6시간)와 분리 — 현황판 날짜별 방문이 늦게 갱신되던 문제."""
    if not _due(strategy, "pages_at", 3 * 3600):
        return False
    try:
        import monetize
        if monetize.collect_pages():
            strategy["pages_at"] = _now()
            return True
    except Exception as e:
        log.warning("Pages 통계 수집 실패: %s", e)
    return False


def evolve(stats: dict | None = None, force: bool = False) -> dict:
    strategy = core.load_strategy()
    if collect_pages_due(strategy):
        core._save_json(core.STRATEGY_PATH, strategy)
    for key in ("prompt_notes", "blocked_feeds", "history"):
        strategy.setdefault(key, [])
    for key in ("keyword_hints", "extra_feeds"):
        strategy.setdefault(key, {})
    cleaned = growth.clean_notes(strategy["prompt_notes"])  # 주제 밖·중복 지침 정리 (다른 사이트 지침 섞임 방지)
    if cleaned != strategy["prompt_notes"]:
        growth.set_notes(strategy, cleaned, "주제 밖·중복 지침 정리") if cleaned else None
        strategy["history"] = (strategy["history"] + [{"at": _now(), "notes_cleaned": cleaned}])[-30:]
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or strategy_due(strategy):
        strategy = update_strategy(strategy)
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "terms_audited_at", TERM_AUDIT_EVERY):
        try:
            learned = audit_terms()
            strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "glossary_learned": learned}])[-30:]
        except Exception as e:
            log.warning("용어 점검 실패: %s", e)
        strategy["terms_audited_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    try:  # AI 관리자: 수락된 제안 반영(매 실행, AI 호출 없음) + 하루 1회 분석·제안(AI 1회)
        import manager
        applied = manager.apply_accepted()
        if applied:
            strategy = core.load_strategy()
            strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "manager_applied": applied}])[-30:]
            core._save_json(core.STRATEGY_PATH, strategy)
        manager.review()
        import site_manager  # 사이트별 AI 관리자 (Pix2Poly·life-after-60): 하루 1회, 뉴스 몫을 남기고
        site_done = site_manager.run_due()
        if site_done:
            strategy = core.load_strategy()
            strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "site_managers": site_done}])[-30:]
            core._save_json(core.STRATEGY_PATH, strategy)
        import staff  # AI 직원(마케터 등): 주기가 된 역할만 일함
        worked = staff.run_due()
        if worked:
            strategy = core.load_strategy()
            strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "staff": worked}])[-30:]
            core._save_json(core.STRATEGY_PATH, strategy)
    except Exception as e:
        log.warning("AI 관리자 실패: %s", e)
    import gsc
    # 검색 데이터는 하루 단위로 확정 → 성공하면 24시간 뒤, 실패하면 3시간 뒤 재시도. 키가 없으면 기록하지 않음(등록 즉시 동작)
    if gsc.enabled() and (force or (_due(strategy, "gsc_ok_at", 24 * 3600) and _due(strategy, "gsc_try_at", 3 * 3600))):
        strategy["gsc_try_at"] = _now()
        try:
            if gsc.collect() is not None:
                strategy["gsc_ok_at"] = _now()
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "gsc": gsc.top_queries(5)}])[-30:]
        except Exception as e:
            log.warning("Search Console 수집 실패: %s", e)
            strategy["gsc_error"] = str(e)[:300]
        else:
            strategy.pop("gsc_error", None)
        core._save_json(core.STRATEGY_PATH, strategy)
    auto = bool(core.load_config().get("auto_mode"))
    plan = {}
    if auto:  # 자동 모드: 매 실행마다 AI 관리자의 오늘 배분량만큼 생성
        try:
            import manager
            plan = manager.plan_today()
        except Exception as e:
            log.warning("자동 배분 실패: %s", e)
            auto = False
    if auto or force or _due(strategy, "guides_at", 3 * 3600):  # 수동: 3시간마다 가이드 제작 (AI 비중 0.5 배분 고려)
        try:
            import guides
            # AI 할당 비중 재조정: news 0.25, guides 0.5, roundups 0.25
            guides_count = plan.get("guides_now", 4) if auto else 4
            made = guides.write_guides(guides_count, gate=False) if auto else guides.write_guides(4)
            if made:
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "guides": made}])[-30:]
        except Exception as e:
            log.warning("기초 가이드 생성 실패: %s", e)
        strategy["guides_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    if auto or force or _due(strategy, "roundups_at", 3 * 3600):  # 3시간마다 점검, 도구별로는 주 1회 갱신
        try:
            made = write_roundups(plan["roundups_now"], gate=False) if auto else write_roundups()
            if made:
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "roundups": made}])[-30:]
        except Exception as e:
            log.warning("도구별 정리 실패: %s", e)
        strategy["roundups_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "enrich_at", 3600):  # 짧은 글 보강: 1시간마다 최대 3개 (AI 여유 50% 이상)
        try:
            import enrich
            made = enrich.enrich_weak(3)
            if made:
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "enriched": made}])[-30:]
        except Exception as e:
            log.warning("글 보강 실패: %s", e)
        strategy["enrich_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "recipes_at", 6 * 3600):  # 실무 파이프라인 레시피: 6시간마다 1개 (AI 여유 50% 이상)
        try:
            import recipes
            made = recipes.write_recipes(1)
            if made:
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "recipes": made}])[-30:]
        except Exception as e:
            log.warning("파이프라인 레시피 생성 실패: %s", e)
        strategy["recipes_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "refs_at", 3 * 3600):  # 오류 해결·버전별 바뀐 점: 3시간마다 조금씩 (하루 상한)
        try:
            import refs
            made = refs.write(2, 1)
            if made:
                strategy["history"] = (strategy.get("history", []) + [{"at": _now(), "refs": made}])[-30:]
        except Exception as e:
            log.warning("오류 해결·바뀐 점 생성 실패: %s", e)
        strategy["refs_at"] = _now()
        core._save_json(core.STRATEGY_PATH, strategy)
    if force or _due(strategy, "taxonomy_updated_at", TAXONOMY_EVERY):
        strategy = refine_taxonomy(strategy)
        core._save_json(core.STRATEGY_PATH, strategy)
    return strategy


if __name__ == "__main__":
    print(json.dumps(evolve(force=True), ensure_ascii=False, indent=2))
