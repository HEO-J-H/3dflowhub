"""SEO 구조 점검 (빌드된 _site 기준) — 구글이 페이지를 '중복'으로 버리거나 못 찾는 원인을 숫자로.

1) 페이지마다 <title>·meta description·<h1> 이 고유한가 (검색되는 페이지만, noindex 제외)
2) sitemap.xml 에 검색되는 페이지가 빠짐없이 있는가, noindex 페이지가 잘못 들어가 있지 않은가
3) 내부 링크: 홈에서 링크를 따라가 닿을 수 있는가(고아 페이지), 클릭 깊이
결과는 memory/seo_audit.json 에 저장 → 현황판·AI 관리자가 보고, CI 빌드는 심각한 문제가 있으면 경고.
"""
from __future__ import annotations

import json
import re
from collections import Counter, deque
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import core

SITE = core.ROOT / "_site"
BASE = "https://heo-j-h.github.io/3dflowhub/"


def _url_of(f: Path, site: Path = SITE) -> str:
    rel = f.relative_to(site).as_posix()
    rel = rel[:-len("index.html")] if rel.endswith("index.html") else rel
    return BASE + rel


def _meta(html: str) -> dict:
    g = lambda p: (m.group(1).strip() if (m := re.search(p, html, re.S | re.I)) else "")  # noqa: E731
    return {"title": g(r"<title>(.*?)</title>"), "desc": g(r'<meta name="description" content="([^"]*)"'),
            "h1": re.sub(r"<[^>]+>", "", g(r"<h1[^>]*>(.*?)</h1>")).strip(),
            "noindex": bool(re.search(r'<meta name="robots" content="noindex', html)),
            "canonical": g(r'<link rel="canonical" href="([^"]+)"')}


def audit(site: Path = SITE) -> dict:
    pages = {}
    links: dict[str, set[str]] = {}
    for f in site.rglob("*.html"):
        if f.name.startswith("google"):
            continue
        html = f.read_text(encoding="utf-8", errors="ignore")
        u = _url_of(f, site)
        pages[u] = _meta(html)
        out = set()
        for h in re.findall(r'href="([^"#?]+)', html):
            full = unquote(urljoin(u, h))
            if full.startswith(BASE):
                full = full if full.endswith((".html", "/", ".xml")) else full + "/"
                out.add(full)
        links[u] = out
    indexable = {u: m for u, m in pages.items() if not m["noindex"]}
    dup = lambda k: {v: n for v, n in Counter(m[k] for m in indexable.values() if m[k]).items() if n > 1}  # noqa: E731
    sm = {unquote(x) for x in re.findall(r"<loc>([^<]+)</loc>", (site / "sitemap.xml").read_text(encoding="utf-8"))}
    # 홈에서 링크 따라가기 (BFS) — 닿는 깊이
    depth = {BASE: 0}
    q = deque([BASE])
    while q:
        u = q.popleft()
        for v in links.get(u, ()):
            if v in pages and v not in depth:
                depth[v] = depth[u] + 1
                q.append(v)
    orphans = sorted(u for u in indexable if u not in depth)
    deep = sorted(u for u, d in depth.items() if d > 4 and u in indexable)
    res = {
        "pages": len(pages), "indexable": len(indexable),
        "dup_titles": dict(list(dup("title").items())[:20]), "dup_title_count": sum(dup("title").values()),
        "dup_desc_count": sum(dup("desc").values()), "dup_h1_count": sum(dup("h1").values()),
        "missing_h1": sorted(u for u, m in indexable.items() if not m["h1"])[:20],
        "missing_desc": sorted(u for u, m in indexable.items() if not m["desc"])[:20],
        "not_in_sitemap": sorted(u for u in indexable if u not in sm)[:50],
        "not_in_sitemap_count": sum(1 for u in indexable if u not in sm),
        "noindex_in_sitemap": sorted(u for u in sm if u in pages and pages[u]["noindex"])[:20],
        "sitemap_404": sorted(u for u in sm if u not in pages)[:20],
        "orphans": orphans[:50], "orphan_count": len(orphans),
        "max_depth": max(depth.values()) if depth else 0, "deep_pages": len(deep),
    }
    return res


if __name__ == "__main__":
    r = audit()
    core._save_json(core.ROOT / "memory" / "seo_audit.json", r)
    print(json.dumps({k: (v if not isinstance(v, list) else (v[:5], len(v))) for k, v in r.items()}, ensure_ascii=False, indent=1))
