"""출처 자동 발굴 — 사람이 피드 주소를 찾아 넣지 않아도 출처가 계속 늘어나게.

1) 후보: 사이트 주소(튜토리얼·재질·뉴스·포럼·유튜브 채널). 고정 후보(SEEDS) + AI 가 주마다 추천한 후보.
2) 피드 찾기: 페이지의 <link rel="alternate" type="application/rss+xml"> → 흔한 주소(/feed, /rss …) →
   유튜브 채널(@핸들)은 channelId 를 찾아 https://www.youtube.com/feeds/videos.xml?channel_id=… 로.
3) 검증: 실제로 열리고 글이 3개 이상, 최근 60일 안에 글이 있고, 제목·요약의 절반 이상이 3D 어휘와 맞아야 통과.
4) 추가: 통과한 피드를 strategy.json extra_feeds[분야] 에 넣음 → 다음 수집부터 사용.
5) 정리: 연속으로 비거나 실패하는 피드는 blocked_feeds 로 (수집이 느려지지 않게).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

import core

UA = {"User-Agent": "Mozilla/5.0 (3dflowhub source finder)", "Accept-Language": "ko,en;q=0.8"}
LOG_PATH = core.ROOT / "memory" / "sources.json"   # 시도·결과 기록 (같은 후보를 계속 다시 보지 않게)
MIN_ITEMS, MIN_RELEVANT = 3, 0.5
MAX_AGE_DAYS = 60
ASSET_WORDS = ["texture", "textures", "material", "materials", "pbr", "hdri", "seamless", "cc0", "asset", "assets",
               "wood", "stone", "brick", "concrete", "fabric", "metal", "tiles", "ground", "rock", "marble", "plaster",
               "leather", "bark", "sand", "roof", "floor", "terrain", "skybox", "decal", "kitbash", "3d model", "scan",
               "텍스처", "재질", "머티리얼", "에셋"]
COMMON = ("/feed/", "/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/blog/feed/", "/blog/rss.xml", "/index.xml",
          "/latest.rss")

# (분야, 사이트 또는 유튜브 채널 주소) — 튜토리얼·재질·뉴스·커뮤니티·국내
SEEDS: list[tuple[str, str]] = [
    ("3D DCC", "https://www.blenderguru.com/"), ("3D DCC", "https://cgcookie.com/"),
    ("3D DCC", "https://www.creativeshrimp.com/"), ("3D DCC", "https://blenderartists.org/"),
    ("3D DCC", "https://polyhaven.com/"), ("3D DCC", "https://ambientcg.com/"), ("3D DCC", "https://www.cgbookcase.com/"),
    ("3D DCC", "https://www.sharetextures.com/"), ("3D DCC", "https://3dtextures.me/"),
    ("3D DCC", "https://www.maxon.net/en/news"), ("3D DCC", "https://www.foundry.com/news"),
    ("3D DCC", "https://greyscalegorilla.com/blog/"), ("3D DCC", "https://www.thegnomonworkshop.com/news"),
    ("3D DCC", "https://www.therookies.co/"), ("3D DCC", "https://polycount.com/"),
    ("3D DCC", "https://www.youtube.com/@BlenderOfficial"), ("3D DCC", "https://www.youtube.com/@blenderguru"),
    ("3D DCC", "https://www.youtube.com/@Autodesk3dsMax"), ("3D DCC", "https://www.youtube.com/@SideFXHoudini"),
    ("3D DCC", "https://www.youtube.com/@codemod3d"),
    ("Game Engine", "https://www.youtube.com/@UnrealEngine"), ("Game Engine", "https://www.youtube.com/@unity"),
    ("Game Engine", "https://forums.unrealengine.com/"), ("Game Engine", "https://www.gamedeveloper.com/"),
    ("VFX", "https://www.cgw.com/"), ("VFX", "https://www.youtube.com/@fxguide"),
    ("AI 3D", "https://www.youtube.com/@TwoMinutePapers"), ("AI 3D", "https://radiancefields.com/"),
    ("AI 3D", "https://huggingface.co/blog"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url: str, timeout: int = 15) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        return r if r.ok else None
    except requests.RequestException:
        return None


def youtube_feed(url: str) -> str:
    """유튜브 채널 주소(@핸들·/channel/ID) → 영상 피드 주소."""
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if m:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
    r = _get(url)
    if not r:
        return ""
    # 그 채널 자신의 ID 를 먼저 (페이지 안의 다른 채널 ID 를 집지 않도록 canonical·externalId 우선)
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', r.text) or \
        re.search(r'"externalId":"(UC[\w-]{22})"', r.text) or \
        re.search(r'"channelId":"(UC[\w-]{22})"', r.text)
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}" if m else ""


def find_feeds(url: str) -> list[str]:
    """사이트 주소 → 피드 후보 주소들 (확실한 것 먼저)."""
    if "youtube.com" in url:
        f = youtube_feed(url)
        return [f] if f else []
    out = []
    r = _get(url)
    if r:
        for m in re.finditer(r"<link[^>]+>", r.text[:200000], re.I):
            tag = m.group(0)
            if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
                h = re.search(r'href=["\']([^"\']+)', tag)
                if h:
                    out.append(urljoin(r.url, h.group(1)))
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    path = urlparse(url).path.rstrip("/")
    out += [base + path + c for c in COMMON if path] + [base + c for c in COMMON]
    return list(dict.fromkeys(out))


def check_feed(feed_url: str) -> dict:
    """{'ok', 'items', 'relevant', 'newest_days', 'title'} — 3D 관련 피드인지 실제 내용으로 판단."""
    try:
        feed = core.fetch_feed(feed_url)
    except Exception as e:
        return {"ok": False, "why": f"열리지 않음: {type(e).__name__}"}
    es = list(feed.entries or [])[:25]
    if len(es) < MIN_ITEMS:
        return {"ok": False, "why": f"글이 {len(es)}개뿐"}
    vocab = core.relevance_vocab() + ASSET_WORDS  # 텍스처·재질·HDRI·에셋도 3D 작업자를 모으는 주제
    rel = sum(1 for e in es if core.prefilter_score(f"{e.get('title', '')} {e.get('summary', '')[:400]}", vocab)) / len(es)
    newest = None
    for e in es:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            d = (time.time() - time.mktime(t)) / 86400
            newest = d if newest is None else min(newest, d)
    res = {"items": len(es), "relevant": round(rel, 2), "newest_days": None if newest is None else round(newest, 1),
           "title": str(getattr(feed, "feed", {}).get("title", ""))[:80]}
    if rel < MIN_RELEVANT:
        return {**res, "ok": False, "why": f"3D 관련 글 비율 {rel:.0%}"}
    if newest is not None and newest > MAX_AGE_DAYS:
        return {**res, "ok": False, "why": f"최근 {MAX_AGE_DAYS}일 새 글 없음"}
    return {**res, "ok": True}


def current_feeds() -> set[str]:
    s = core.load_strategy()
    fs = {f for d in core.DOMAINS.values() for f in d["feeds"]}
    fs |= {f for lst in (s.get("extra_feeds") or {}).values() for f in lst}
    return {core.normalize_feed_url(f) for f in fs}


def suggest_sites(n: int = 12) -> list[tuple[str, str]]:
    """AI 에게 아직 없는 출처(사이트·유튜브 채널) 주소를 추천받음 — 검증은 check_feed 가 함 (추천만으론 안 넣음)."""
    tried = list(core._load_json(LOG_PATH, {}).get("tried", {}).keys())
    prompt = ("Suggest websites and YouTube channels that regularly publish 3D/CG content useful to Korean 3D artists: "
              "tutorials (Blender, 3ds Max, Maya, Houdini, ZBrush, Substance, Unreal, Unity, Omniverse), free PBR "
              "material/HDRI/asset sites with news or blogs, studio breakdowns, Korean-language 3D YouTube channels and blogs.\n"
              f"Already tried (do not repeat): {tried[-120:]}\n"
              f'Return JSON {{"sites": [{{"domain": one of {list(core.DOMAINS)}, "url": homepage or youtube channel URL '
              f'(https://www.youtube.com/@handle)}}]}} — {n} items, only URLs you are confident exist.')
    try:
        out = core._parse_json(core.llm(prompt, max_tokens=900, json_mode=True))
    except Exception:
        return []
    return [(str(x.get("domain")), str(x.get("url"))) for x in (out.get("sites") or [])
            if isinstance(x, dict) and x.get("domain") in core.DOMAINS and str(x.get("url", "")).startswith("http")]


def discover(candidates: list[tuple[str, str]] | None = None, limit: int = 15, use_ai: bool = True) -> list[str]:
    """후보 사이트에서 피드를 찾아 검증하고, 통과한 것을 수집 목록에 추가. 추가된 피드 설명 목록 반환."""
    log = core._load_json(LOG_PATH, {"tried": {}, "added": []})
    have = current_feeds()
    cands = candidates if candidates is not None else (SEEDS + (suggest_sites() if use_ai and core.background_ok(1) else []))
    cands = [c for c in cands if c[1] not in log["tried"]][:limit]
    strategy = core.load_strategy()
    extra = strategy.setdefault("extra_feeds", {})
    added = []
    for domain, site in cands:
        result = {"at": _now(), "domain": domain, "feed": "", "why": "피드를 찾지 못함"}
        for f in find_feeds(site)[:8]:
            if core.normalize_feed_url(f) in have:
                result.update(feed=f, why="이미 수집 중")
                break
            chk = check_feed(f)
            if chk.get("ok"):
                extra.setdefault(domain, []).append(f)
                have.add(core.normalize_feed_url(f))
                result.update(feed=f, why="추가", **{k: chk[k] for k in ("items", "relevant", "newest_days", "title")})
                added.append(f"{domain}: {chk.get('title') or site} ({f})")
                break
            if chk.get("items"):  # 피드는 있었지만 기준 미달 — 이유 기록
                result.update(feed=f, why=chk.get("why", ""))
        log["tried"][site] = result
    if added:
        strategy["extra_feeds"] = extra
        core._save_json(core.STRATEGY_PATH, strategy)
        log["added"] = (log.get("added", []) + [{"at": _now(), "feed": a} for a in added])[-300:]
    core._save_json(LOG_PATH, log)
    return added


def prune(fail_runs: int = 20) -> list[str]:
    """여러 번 연속 비어 있는 추가 피드는 차단 목록으로 (수집 시간 낭비 방지)."""
    stats = core._load_json(core.ROOT / "memory" / "feed_health.json", {})
    strategy = core.load_strategy()
    blocked = set(strategy.get("blocked_feeds", []))
    out = []
    for lst in (strategy.get("extra_feeds") or {}).values():
        for f in lst:
            if stats.get(f, {}).get("empty_streak", 0) >= fail_runs and f not in blocked:
                blocked.add(f)
                out.append(f)
    if out:
        strategy["blocked_feeds"] = sorted(blocked)
        core._save_json(core.STRATEGY_PATH, strategy)
    return out


if __name__ == "__main__":
    import sys
    print(discover(use_ai="--no-ai" not in sys.argv))
