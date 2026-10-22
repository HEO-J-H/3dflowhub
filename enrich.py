"""
글 품질 보강 — 짧은 요약 글에 '실무 적용·커뮤니티 반응·튜토리얼·대안 비교'를 더해 독자 가치를 높인다
==========================================================================================
뉴스 요약만으로는 다른 사이트와 차이가 없고 분량도 짧다(중앙값 약 800자). 그래서 글마다
  1) 참고 자료 수집 — 공개 검색 API 가 있는 커뮤니티·자료만, 제목·짧은 발췌·링크만 사용 (원문 복사 없음)
       · BlenderArtists / Unreal 공식 포럼 / Godot 포럼 (Discourse 검색 API)
       · Hacker News (Algolia API) — AI 3D·연구 소식의 개발자 반응
       · YouTube 튜토리얼 (guides.find_videos, 임베드 허용 영상만)
     (레딧·Polycount 는 비로그인 API 를 막고 있어 사용하지 않음)
  2) AI 가 원문 요약 + 참고 자료를 바탕으로 새 섹션 작성 — 참고 자료에 없는 사실은 쓰지 않게, 커뮤니티 의견은 번호로 출처 표시
  3) 품질 확인 — 보강 후 본문이 기준(1,500자) 미만이거나 섹션이 부실하면 버림
보강한 글은 'enriched_at' 과 참고 링크(refs)를 남기고, 사이트는 '참고한 커뮤니티·튜토리얼' 로 출처를 보여 준다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests

import core

UA = {"User-Agent": "3dflowhub-research/1.0 (+https://heo-j-h.github.io/3dflowhub/)"}
MIN_CHARS = 1500           # 보강 후 본문 최소 분량 (수익화 플레이북 기준)
WEAK_CHARS = 1200          # 이보다 짧으면 보강 대상
DISCOURSE = {
    "BlenderArtists": "https://blenderartists.org",
    "Unreal Engine 포럼": "https://forums.unrealengine.com",
    "Godot 포럼": "https://forum.godotengine.org",
}
STOP = {"the", "and", "for", "with", "new", "how", "from", "into", "your", "you", "this", "that", "now", "are",
        "released", "release", "update", "announces", "announced", "available", "introduces", "video", "free"}


def body_chars(p: dict) -> int:
    return len(p.get("summary") or "") + sum(len(s.get("body") or "") for s in p.get("sections") or [])


def is_weak(p: dict) -> bool:
    return body_chars(p) < WEAK_CHARS and not p.get("enriched_at")


def query_for(p: dict) -> str:
    """검색어: 도구(카테고리) + 원문 영어 제목(없으면 영어 태그)의 핵심 단어 몇 개."""
    text = (p.get("title") or "") + " " + " ".join(t for t in p.get("tags") or [] if re.fullmatch(r"[A-Za-z0-9 .+-]+", t))
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9+.-]{2,}", text) if w.lower() not in STOP]
    tool = "" if str(p.get("category", "")).startswith("기타") else str(p.get("category") or "")
    head = [tool] if re.fullmatch(r"[A-Za-z0-9 .+-]+", tool) else []
    seen = {w.lower() for w in " ".join(head).split()}
    rest = [w for w in dict.fromkeys(words) if w.lower() not in seen and not seen.add(w.lower())]
    q = " ".join(head + rest[:4])
    return q.strip()


def forums_for(p: dict) -> list[str]:
    text = f"{p.get('domain')} {p.get('category')} {p.get('title')}".lower()
    out = []
    if "unreal" in text or "언리얼" in text:
        out.append("Unreal Engine 포럼")
    if "godot" in text:
        out.append("Godot 포럼")
    if not out or "blender" in text or p.get("domain") in ("3D DCC", "VFX", "AI 3D"):
        out.append("BlenderArtists")
    return out


def discourse_refs(site: str, q: str, n: int = 3) -> list[dict]:
    base = DISCOURSE[site]
    try:
        r = requests.get(f"{base}/search.json", params={"q": q}, headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []
    blurbs = {}
    for post in data.get("posts") or []:
        blurbs.setdefault(post.get("topic_id"), post.get("blurb") or "")
    out = []
    for t in sorted(data.get("topics") or [], key=lambda t: -(t.get("posts_count") or 0)):
        if (t.get("posts_count") or 0) < 2:
            continue  # 답이 없는 글은 반응이 아님
        out.append({"source": site, "title": t.get("title", "")[:120],
                    "url": f"{base}/t/{t.get('slug')}/{t.get('id')}",
                    "excerpt": re.sub(r"\s+", " ", blurbs.get(t.get("id"), ""))[:300],
                    "replies": t.get("posts_count", 0) - 1})
        if len(out) >= n:
            break
    return out


def hn_refs(q: str, n: int = 2) -> list[dict]:
    try:
        hits = requests.get("https://hn.algolia.com/api/v1/search", params={"query": q, "tags": "story"},
                            headers=UA, timeout=20).json().get("hits") or []
    except (requests.RequestException, ValueError):
        return []
    out = []
    for h in hits:
        if (h.get("num_comments") or 0) >= 5:
            out.append({"source": "Hacker News", "title": (h.get("title") or "")[:120],
                        "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                        "excerpt": f"점수 {h.get('points', 0)} · 댓글 {h.get('num_comments', 0)}",
                        "replies": h.get("num_comments", 0)})
        if len(out) >= n:
            break
    return out


def gather(p: dict) -> tuple[list[dict], list[dict]]:
    q = query_for(p)
    if not q:
        return [], []
    refs: list[dict] = []
    for site in forums_for(p):
        refs += discourse_refs(site, q)
    if p.get("domain") in ("AI 3D", "VFX") or p.get("topic") == "연구·논문":
        refs += hn_refs(q)
    try:
        import guides
        videos = guides.find_videos(f"{q} tutorial", n=2)
    except Exception:
        videos = []
    return [r for r in refs if relevant(r, q)][:6], videos


def relevant(r: dict, q: str) -> bool:
    """검색어 핵심 단어가 토론 제목·발췌에 실제로 있어야 참고 자료로 씀 (엉뚱한 글 걸러내기)."""
    keys = [w.lower() for w in q.split() if len(w) > 2]
    text = f"{r.get('title', '')} {r.get('excerpt', '')}".lower()
    return len(keys) >= 2 and sum(k in text for k in keys) >= 2  # 단어 하나짜리 검색은 너무 넓어서 제외


_NUM = re.compile(r"(?<![\[\w.])(\d[\d,]*(?:\.\d+)?)\s*(억|만|천|개|%|달러|원|배|년|시간|분|초|GB|TB|MB|fps|ms|K|B)?(?!\])")


def _nums(text: str) -> set[tuple[str, str]]:
    return {(n.replace(",", ""), u or "") for n, u in _NUM.findall(text)}


def unsupported_numbers(text: str, source: str) -> list[str]:
    """보강 글의 숫자(버전·가격·개수·파라미터 등)가 원문·참고 자료에 단위까지 같게 없으면 지어낸 것으로 본다.
    예: 원문 '300억' → 보강 '30억'. 인용 번호 [1] 과 단위 없는 한 자리 숫자(단계 번호 등)는 제외."""
    src = _nums(source)
    bad = []
    for n, u in sorted(_nums(text)):
        if not u and len(n.replace(".", "")) < 2:
            continue
        if (n, u) not in src and not (not u and any(n == m for m, _ in src)):
            bad.append(n + u)
    return bad


def enrich_post(p: dict) -> dict | None:
    """보강된 글(사본)을 돌려줌. 품질 기준 미달이면 None."""
    refs, videos = gather(p)
    numbered = [{"n": i + 1, **{k: r[k] for k in ("source", "title", "excerpt")}} for i, r in enumerate(refs)]
    prompt = (
        f"Korean article (summary of {p.get('url')}):\n"
        + json.dumps({"title": p.get("title_ko"), "summary": p.get("summary"), "sections": p.get("sections"),
                      "domain": p.get("domain"), "tool": p.get("category")}, ensure_ascii=False)[:3500]
        + f"\n\nCommunity discussions found (numbered):\n{json.dumps(numbered, ensure_ascii=False)}\n"
        + f"Tutorial videos found: {json.dumps([v['title'] for v in videos], ensure_ascii=False)}\n\n"
        "Improve this article for Korean 3D artists so it is genuinely useful, not just news. Add NEW sections only "
        "(do not repeat the existing text). Rules: use only facts from the article and the discussions; never invent "
        "versions, prices, dates or features; when you use a discussion, cite it like [1]; if discussions are empty "
        "or irrelevant, skip the community section. Keep official English product/menu names.\nReturn JSON:\n"
        ' "sections": 2-4 {"heading": Korean, "body": Korean 250-600 chars} chosen from: '
        '"실무에서 이렇게 씁니다" (concrete workflow steps), "커뮤니티 반응과 주의점" (only from discussions, with [n]), '
        '"비슷한 도구·대안과 비교", "시작하려면" (what to install/learn first),\n'
        ' "faq": 1-2 {"q","a"} new practical questions,\n'
        ' "used_refs": list of discussion numbers you actually used'
    )
    try:
        out = core._parse_json(core.llm(prompt, system="You are a senior 3D production mentor and careful editor."
                                        + core.playbook("common", "editor", limit=3000),
                                        max_tokens=2200, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:
        core.log.warning("글 보강 실패 %s: %s", p.get("id"), e)
        return None
    if not isinstance(out, dict):
        return None
    fx = core.fix_terms
    new = [{"heading": fx(str(s.get("heading", "")))[:60], "body": fx(str(s.get("body", "")))[:900], "added": True}
           for s in out.get("sections") or [] if isinstance(s, dict) and len(str(s.get("body", ""))) >= 120][:4]
    source = json.dumps([p.get("title_ko"), p.get("summary"), p.get("sections"),
                         [(r["title"], r["excerpt"]) for r in refs if r["source"] != "Hacker News"]], ensure_ascii=False)
    kept = [s for s in new if not unsupported_numbers(s["body"], source)]
    if len(kept) < len(new):
        core.log.info("보강 섹션 %d개 버림 (원문에 없는 숫자): %s", len(new) - len(kept), p.get("id"))
    new = kept
    used = {int(n) for n in out.get("used_refs") or [] if str(n).isdigit()}
    q = dict(p)
    q["sections"] = list(p.get("sections") or []) + new
    q["faq"] = list(p.get("faq") or []) + [{"q": fx(str(f.get("q", ""))), "a": fx(str(f.get("a", "")))}
                                           for f in out.get("faq") or [] if isinstance(f, dict) and f.get("q")][:2]
    if len(new) < 2 or body_chars(q) < MIN_CHARS:
        core.log.info("보강 품질 미달 %s: 섹션 %d, %d자", p.get("id"), len(new), body_chars(q))
        return None
    q["refs"] = [refs[i - 1] for i in sorted(used) if 0 < i <= len(refs)] or \
        ([] if not any("[" in s["body"] for s in new) else refs)
    q["videos"] = videos
    q["enriched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    q["quality"] = {"before": body_chars(p), "after": body_chars(q)}
    return q


def enrich_weak(max_n: int = 3, gate: bool = True) -> list[str]:
    """짧은 글을 최신순으로 몇 개씩 보강 (AI 여유 50% 이상일 때만)."""
    if max_n <= 0 or (gate and not core.background_ok(max_n * 2)):  # 뉴스 수집 몫을 남기고
        return []
    hidden = {k for k, v in core.curation_state().items() if v == "hide"}
    posts = []
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        if p.get("title_ko") and f.stem not in hidden and is_weak(p):
            posts.append((p.get("collected_at") or "", f, p))
    done = []
    for _, f, p in sorted(posts, key=lambda t: t[0], reverse=True)[:max_n * 2]:
        if len(done) >= max_n:
            break
        try:
            q = enrich_post(p)
        except core.LLMBudgetExceeded:
            break
        if q:
            core._save_json(f, q)
            done.append(f"{p['title_ko'][:40]} ({q['quality']['before']}→{q['quality']['after']}자)")
        else:  # 다시 시도하지 않도록 표시 (참고 자료가 없거나 품질 미달)
            p["enriched_at"] = "skip"
            core._save_json(f, p)
    return done
