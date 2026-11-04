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



# ── 연구 논문(arXiv) — 일반 보강과 다르게: 원문 전체를 근거로 정확하게, 지어낸 '실무 워크플로' 금지 ──
# (검토 2026-11-03: 논문 글에 '실무에서 이렇게 씁니다' 가 붙어 논문에 없는 Blender·Houdini 작업 순서를 지어냈고,
#  제목으로 찾은 영상이 종이접기 공작 영상이었음 → 논문은 이 경로로만 고친다)
def is_paper(p: dict) -> bool:
    return "arxiv.org" in (p.get("url") or "") or p.get("topic") == "연구·논문"


def paper_source(url: str) -> dict:
    """arXiv 본문(HTML판)·그림 설명·코드 링크·라이선스. 그림은 CC 라이선스 논문만 가져옴 (재사용 허락)."""
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([\d.]+(?:v\d+)?)", url or "")
    if not m:
        return {}
    aid = m.group(1)
    out = {"id": aid, "text": "", "figures": [], "code": [], "license": ""}
    try:
        from bs4 import BeautifulSoup
        abs_html = requests.get(f"https://arxiv.org/abs/{aid}", headers=UA, timeout=20).text
        lic = re.search(r'href="(https?://(?:creativecommons\.org|arxiv\.org/licenses)[^"]+)"', abs_html)
        out["license"] = lic.group(1) if lic else ""
        base = f"https://arxiv.org/html/{aid}" + ("" if re.search(r"v\d+$", aid) else "v1") + "/"
        soup = BeautifulSoup(requests.get(base, headers=UA, timeout=30).text, "html.parser")
        for t in soup.select(".ltx_bibliography, script, style, nav"):
            t.decompose()
        out["text"] = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:16000]
        out["code"] = sorted(set(re.findall(r"https?://github\.com/[\w.-]+/[\w.-]+", str(soup))))[:3]
        if "creativecommons.org" in out["license"]:
            from urllib.parse import urljoin
            for fig in soup.find_all("figure"):
                img, cap = fig.find("img"), fig.find("figcaption")
                if img and img.get("src") and cap:
                    out["figures"].append({"src": urljoin(base, img["src"]), "caption": cap.get_text(" ", strip=True)[:300]})
                if len(out["figures"]) >= 4:
                    break
    except Exception as e:  # noqa: BLE001
        core.log.warning("논문 본문 읽기 실패 %s: %s", url, e)
    return out


def rewrite_paper(p: dict) -> dict | None:
    """논문 글을 원문 전체 기준으로 다시 씀 — 문제·핵심 아이디어·방법·결과(논문 수치)·한계·공개 여부."""
    src = paper_source(p.get("url", ""))
    if len(src.get("text", "")) < 2000:
        return None
    figs = src["figures"]
    prompt = (f"Research paper full text (ground truth):\n{src['text']}\n\n"
              f"Code links found in paper: {src['code'] or 'none'}\n"
              + (f"Figure captions (English): {json.dumps([f['caption'] for f in figs], ensure_ascii=False)}\n" if figs else "")
              + "Write an accurate Korean explainer for Korean 3D artists. Rules: only facts from the paper; quote the paper's "
              "own numbers exactly; do NOT invent tool workflows, menu paths or plugins (the paper did not use Blender etc. "
              "unless it says so); clearly separate what the paper showed vs. possible uses (mark as 가능성). Translate "
              "terms correctly (origami = 종이접기/오리가미, never 오리기). Keep English technical terms in parentheses once.\n"
              "Return JSON:\n"
              ' "title_ko": 25-45 chars, what the paper does,\n'
              ' "summary": 1 sentence,\n'
              ' "sections": 5-6 {"heading","body"} — 무엇을 풀려는가 / 핵심 아이디어 / 방법 (단계) / 결과 (논문 수치) / '
              'Limitations·아직 못 하는 것 / 코드·데이터 공개 여부,\n'
              ' "insight": 2-4 sentences — what this could mean for 3D artists (가능성, not fact),\n'
              ' "faq": 2 {"q","a"} answered from the paper only (never cite our own section names as the paper\'s),\n'
              ' "try_it": steps only if code or demo is public (with the link), else [],\n'
              ' "tags": 3-6 short Korean/English tags,\n'
              + (' "figure_captions_ko": one short Korean caption per figure, same order' if figs else ""))
    try:
        out = core._parse_json(core.llm(prompt, system="You are a precise science editor for a Korean 3D learning site."
                                        + core.playbook("common", "editor", limit=6000), max_tokens=3200, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("논문 글 다시 쓰기 실패 %s: %s", p.get("id"), e)
        return None
    fx = core.fix_terms
    secs = [{"heading": fx(str(x.get("heading", "")))[:60], "body": fx(str(x.get("body", "")))[:1200]}
            for x in out.get("sections") or [] if isinstance(x, dict) and len(str(x.get("body", ""))) >= 60]
    bad = unsupported_numbers(" ".join(x["body"] for x in secs), src["text"])
    if len(secs) < 4 or len(bad) > 2:  # 논문에 없는 숫자가 여럿이면 버림
        core.log.info("논문 글 다시 쓰기 품질 미달 %s: 섹션 %d, 근거 없는 숫자 %s", p.get("id"), len(secs), bad[:5])
        return None
    q = dict(p)
    q.update({"title_ko": fx(str(out.get("title_ko") or p.get("title_ko")))[:60], "summary": fx(str(out.get("summary") or "")),
              "sections": secs, "insight": fx(str(out.get("insight") or "")),
              "faq": [{"q": fx(str(f.get("q", ""))), "a": fx(str(f.get("a", "")))} for f in out.get("faq") or []
                      if isinstance(f, dict) and f.get("q")][:3],
              "try_it": [core.step_text(t) for t in out.get("try_it") or [] if core.step_text(t)][:4] if src["code"] else [],
              "tags": [str(t)[:30] for t in out.get("tags") or p.get("tags") or []][:6],
              "refs": [], "videos": [], "paper": {"code": src["code"], "license": src["license"]},
              "paper_v": 2, "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    caps = out.get("figure_captions_ko") or []
    if figs:
        q["media"] = {**(p.get("media") or {}), "figures": [{**f, "caption_ko": str(caps[i])[:120] if i < len(caps) else ""}
                                                              for i, f in enumerate(figs)]}
    q.pop("qa_at", None)
    return q


def fix_papers(max_n: int = 3) -> list[str]:
    """예전 방식으로 보강·요약된 논문 글을 다시 씀 (최신부터, 하루 몇 개씩)."""
    if not core.background_ok(max_n * 2):
        return []
    hidden = {k for k, v in core.curation_state().items() if v == "hide"}
    done = []
    for f in sorted(core.POSTS_DIR.glob("*.json"), reverse=True):
        if len(done) >= max_n:
            break
        p = core._load_json(f, {})
        if not is_paper(p) or p.get("paper_v") or p.get("id") in hidden or p.get("paper_tried"):
            continue
        try:
            q = rewrite_paper(p)
        except core.LLMBudgetExceeded:
            break
        if q:
            core._save_json(f, q)
            done.append(q["id"])
        else:
            p["paper_tried"] = True
            core._save_json(f, p)
    return done

def enrich_post(p: dict) -> dict | None:
    """보강된 글(사본)을 돌려줌. 품질 기준 미달이면 None."""
    if is_paper(p):  # 논문은 원문 전체 기준으로 다시 쓰기 (지어낸 실무 섹션·엉뚱한 영상 방지)
        return rewrite_paper(p)
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
        ' "sections": 1-3 {"heading": Korean, "body": Korean 200-600 chars} - only when the article or the '
        'discussions give concrete material: usage steps the SOURCE itself describes, community reactions (with [n]), '
        'a comparison the sources support, or setup requirements stated in the source. Headings must be specific '
        'to this article (name the tool, feature or problem), never generic labels like 시작하려면, 실무에서 이렇게 '
        '씁니다, 개요. If nothing concrete can be added, return an empty list,\n'
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
    if len(new) < 1 or body_chars(q) < MIN_CHARS:
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
