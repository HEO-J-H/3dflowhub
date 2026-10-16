"""
3dflowhub GitHub Pages 사이트 생성기
====================================
content/posts/*.json (노션과 같은 내용) → _site/ 정적 사이트

  python build_site.py              # _site/ 생성
  python build_site.py --backfill   # 노션에 있는데 JSON 이 없는 글을 노션 블록에서 복원 후 생성

구성
  /                         최신 글 + 카테고리 게시판 목록
  /c/<도메인>/              도메인 게시판 (세부 카테고리 탭)
  /c/<도메인>/<세부>/       세부 카테고리 게시판
  /p/<id>.html              글 (대표 이미지·영상·요약·본문·에디터 코멘트·FAQ·관련 글·원문)
  /search.json /feed.xml /sitemap.xml /robots.txt

배포: .github/workflows/pages.yml (저장소 Settings → Pages → Source: GitHub Actions)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import core

ROOT = Path(__file__).parent
OUT = ROOT / "_site"
SITE_TITLE = "3dflowhub"
SITE_DESC = "3D DCC · 게임 엔진 · VFX · AI 3D 최신 소식을 한국어로 요약·정리합니다."
BASE_URL = "https://heo-j-h.github.io/3dflowhub"  # 커스텀 도메인 연결 시 변경
PAGE_SIZE = 30
DOMAIN_SLUG = {"3D DCC": "3d-dcc", "Game Engine": "game-engine", "VFX": "vfx", "AI 3D": "ai-3d"}
DOMAIN_ICON = {"3D DCC": "🧊", "Game Engine": "🎮", "VFX": "💥", "AI 3D": "🤖"}
e = html.escape


def slug(name: str) -> str:
    s = re.sub(r"[\s/·]+", "-", name.strip())
    s = re.sub(r"[^\w\-가-힣]", "", s)
    return s.strip("-").lower() or "etc"


def cat_url(domain: str, sub: str | None = None) -> str:
    base = f"c/{DOMAIN_SLUG.get(domain, slug(domain))}/"
    return base + (f"{quote(slug(sub))}/" if sub else "")


# ─────────────────────────── 데이터 ───────────────────────────
def load_posts() -> list[dict]:
    posts = []
    for f in sorted(core.POSTS_DIR.glob("*.json")):
        p = core._load_json(f, None)
        if isinstance(p, dict) and p.get("title_ko"):
            p.setdefault("id", f.stem)
            posts.append(p)
    posts.sort(key=lambda p: p.get("collected_at") or "", reverse=True)
    # 여러 글이 같은 이미지를 쓰면 사이트 로고/기본 썸네일 → 숨김
    freq: dict[str, int] = defaultdict(int)
    for p in posts:
        freq[(p.get("media") or {}).get("image") or ""] += 1
    for p in posts:
        m = p.get("media") or {}
        if m.get("image") and (freq[m["image"]] >= 3 or core.is_generic_image(m["image"])):
            p["media"] = {**m, "image": ""}
    return posts


def _text(rich: list) -> str:
    return "".join(t.get("plain_text", "") for t in rich or [])


def _retry(fn, *a, **k):
    """노션 429(rate limit) 시 지수 백오프 재시도."""
    for i in range(6):
        try:
            return fn(*a, **k)
        except Exception as ex:
            if "rate limit" not in str(ex).lower() or i == 5:
                raise
            time.sleep(2 ** i)


def backfill_from_notion(limit: int = 500) -> int:
    """노션 페이지 블록에서 글을 복원해 JSON 으로 저장 (이미 있으면 건너뜀)."""
    client = core._notion()
    if client is None:
        return 0
    existing = {core._load_json(f, {}).get("url") for f in core.POSTS_DIR.glob("*.json")}
    n, cursor = 0, None
    while n < limit:
        body = {"page_size": 50, **({"start_cursor": cursor} if cursor else {})}
        res = _retry(core._query_db, client, body)
        for page in res["results"]:
            pr = page["properties"]
            url = pr["URL"]["url"]
            if not url or url in existing:
                continue
            item = {
                "title_ko": _text(pr["Name"]["title"]), "title": "", "url": url,
                "domain": (pr["Domain"]["select"] or {}).get("name", "3D DCC"),
                "category": (pr.get("Category", {}).get("select") or {}).get("name", ""),
                "tags": [t["name"] for t in pr["Tags"]["multi_select"]],
                "summary": _text(pr["Summary"]["rich_text"]),
                "collected_at": (pr["CollectedAt"]["date"] or {}).get("start", ""),
                "notion_id": page["id"], "insight": "", "sections": [], "faq": [],
                "media": {"image": ((pr.get("Thumbnail", {}).get("files") or [{}])[0].get("external") or {}).get("url", ""),
                          "video": pr.get("Video", {}).get("url") or ""},
            }
            heading = None
            time.sleep(0.4)  # 노션 3 req/s 제한
            for b in _retry(client.blocks.children.list, block_id=page["id"], page_size=100)["results"]:
                t = b["type"]
                if t == "callout":
                    item["insight"] = _text(b["callout"]["rich_text"])
                elif t == "heading_2":
                    heading = _text(b["heading_2"]["rich_text"])
                elif t == "paragraph" and heading and "자주 묻는" not in heading:
                    item["sections"].append({"heading": heading, "body": _text(b["paragraph"]["rich_text"])})
                elif t == "toggle":
                    time.sleep(0.4)
                    kids = _retry(client.blocks.children.list, block_id=b["id"])["results"]
                    a = " ".join(_text(k[k["type"]].get("rich_text", [])) for k in kids if k["type"] == "paragraph")
                    item["faq"].append({"q": _text(b["toggle"]["rich_text"]).removeprefix("Q. "), "a": a})
            if item["sections"]:
                core.save_post_json(item)
                existing.add(url)
                n += 1
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]
    return n


# ─────────────────────────── 템플릿 ───────────────────────────
CSS = """
:root{--bg:#f7f7f9;--card:#fff;--text:#1d1f24;--muted:#6b7280;--line:#e5e7eb;--accent:#4f46e5;--accent-soft:#eef2ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e7e9ee;--muted:#9aa3b2;--line:#262b36;--accent:#8b8cff;--accent-soft:#1f2240}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR","Malgun Gothic",sans-serif}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
header{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.top{display:flex;align-items:center;gap:16px;height:60px}.logo{font-weight:800;font-size:20px}
.search{margin-left:auto;flex:0 1 280px}.search input{width:100%;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text)}
nav.domains{display:flex;gap:6px;overflow-x:auto;padding:8px 0}nav.domains a{padding:6px 12px;border-radius:999px;white-space:nowrap;font-size:14px;border:1px solid var(--line)}
nav.domains a.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0}.tabs a{font-size:13px;padding:4px 10px;border-radius:6px;background:var(--accent-soft)}
.tabs a.on{background:var(--accent);color:#fff}.tabs .n{opacity:.7;margin-left:4px}
h1{font-size:26px;margin:28px 0 8px}.desc{color:var(--muted);margin:0 0 12px}
.board{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.row{display:grid;grid-template-columns:88px 1fr 130px 92px;gap:14px;align-items:center;padding:12px 16px;border-top:1px solid var(--line)}
.row:first-child{border-top:0}.row img,.row .ph{width:88px;height:56px;object-fit:cover;border-radius:6px;background:var(--accent-soft)}
.row .t{font-weight:600}.row .s{color:var(--muted);font-size:13px;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.badge{font-size:12px;color:var(--accent)}.date{color:var(--muted);font-size:13px;text-align:right}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin:12px 0 28px}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}.box h3{margin:0 0 8px;font-size:17px}
.box ul{margin:0;padding-left:18px;font-size:14px}.box .more{display:inline-block;margin-top:8px;font-size:13px;color:var(--accent)}
.pager{display:flex;gap:6px;justify-content:center;margin:20px 0}.pager a{padding:4px 10px;border:1px solid var(--line);border-radius:6px}.pager a.on{background:var(--accent);color:#fff}
article{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;margin:24px 0}
article h1{margin-top:0}article h2{font-size:20px;margin-top:28px}article img{max-width:100%;border-radius:8px}
.crumb{font-size:13px;color:var(--muted)}.lead{background:var(--accent-soft);border-radius:8px;padding:12px 16px}
.video{position:relative;padding-top:56.25%;margin:16px 0}.video iframe{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:8px}
blockquote{border-left:4px solid var(--accent);margin:0;padding:8px 16px;background:var(--accent-soft);border-radius:0 8px 8px 0}
figcaption{color:var(--muted);font-size:13px;text-align:center}.tags a{font-size:13px;color:var(--muted);margin-right:8px}
details{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}summary{cursor:pointer;font-weight:600}
footer{color:var(--muted);font-size:13px;text-align:center;padding:32px 0}
@media (max-width:640px){.row{grid-template-columns:64px 1fr}.row img,.row .ph{width:64px;height:44px}.row .badge,.row .date{display:none}.search{flex-basis:140px}}
"""

SEARCH_JS = """
const q=document.getElementById('q');let idx=null;
q&&q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();const box=document.getElementById('results');
if(!v){box.innerHTML='';box.hidden=true;return}
idx=idx||await (await fetch(ROOT+'search.json')).json();
const hits=idx.filter(p=>(p.t+' '+p.c+' '+p.g).toLowerCase().includes(v)).slice(0,30);
box.hidden=false;box.innerHTML=hits.length?hits.map(p=>`<a class="row" href="${ROOT}p/${p.i}.html"><span class="ph"></span><span><span class="t">${p.t}</span><br><span class="s">${p.c}</span></span></a>`).join(''):'<div class="row">검색 결과 없음</div>'});
"""


def page(title: str, body: str, root: str, domain_on: str = "", desc: str = SITE_DESC, canonical: str = "") -> str:
    nav = "".join(f'<a href="{root}{cat_url(d)}" class="{"on" if d == domain_on else ""}">{DOMAIN_ICON[d]} {e(d)}</a>'
                  for d in core.DOMAINS)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc[:150])}">
{f'<link rel="canonical" href="{e(canonical)}">' if canonical else ''}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc[:150])}">
<link rel="alternate" type="application/rss+xml" title="{SITE_TITLE}" href="{root}feed.xml">
<link rel="stylesheet" href="{root}assets/style.css"></head><body>
<header><div class="wrap"><div class="top"><a class="logo" href="{root}">🧊 {SITE_TITLE}</a>
<div class="search"><input id="q" type="search" placeholder="제목·카테고리·태그 검색"></div></div>
<nav class="domains"><a href="{root}" class="{"on" if not domain_on else ""}">전체</a>{nav}</nav></div></header>
<main class="wrap"><div id="results" class="board" hidden style="margin-top:16px"></div>{body}</main>
<footer>© {datetime.now():%Y} {SITE_TITLE} · 원문 저작권은 각 출처에 있습니다 · <a href="{root}feed.xml">RSS</a></footer>
<script>const ROOT="{root}";{SEARCH_JS}</script></body></html>"""


def row(p: dict, root: str) -> str:
    img = (p.get("media") or {}).get("image")
    thumb = f'<img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if img else '<span class="ph"></span>'
    return (f'<a class="row" href="{root}p/{p["id"]}.html">{thumb}<span><span class="t">{e(p["title_ko"])}</span><br>'
            f'<span class="s">{e(p.get("summary") or "")}</span></span>'
            f'<span class="badge">{e(p["domain"])} › {e(p.get("category") or "기타")}</span>'
            f'<span class="date">{(p.get("collected_at") or "")[:10]}</span></a>')


def board_pages(posts: list[dict], out_dir: Path, root: str, title: str, header: str, domain_on: str) -> None:
    """게시판 목록 (페이지네이션: index.html, page/2/ ...)."""
    pages = [posts[i:i + PAGE_SIZE] for i in range(0, max(len(posts), 1), PAGE_SIZE)] or [[]]
    for n, chunk in enumerate(pages, 1):
        r = root + ("../../" if n > 1 else "")
        pager = "".join(f'<a class="{"on" if k == n else ""}" href="{r}{out_dir.relative_to(OUT).as_posix()}/'
                        f'{"" if k == 1 else f"page/{k}/"}">{k}</a>' for k in range(1, len(pages) + 1)) \
            if len(pages) > 1 else ""
        body = header.replace("{ROOT}", r) + '<div class="board">' + ("".join(row(p, r) for p in chunk)
                                                                       or '<div class="row">아직 글이 없습니다.</div>') \
            + f'</div><div class="pager">{pager}</div>'
        d = out_dir if n == 1 else out_dir / "page" / str(n)
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page(f"{title} - {SITE_TITLE}", body, r, domain_on), encoding="utf-8")


def post_html(p: dict, root: str, related: list[dict]) -> str:
    m = p.get("media") or {}
    parts = [f'<div class="crumb"><a href="{root}{cat_url(p["domain"])}">{e(p["domain"])}</a> › '
             f'<a href="{root}{cat_url(p["domain"], p.get("category"))}">{e(p.get("category") or "기타")}</a> · '
             f'{(p.get("collected_at") or "")[:10]}</div><h1>{e(p["title_ko"])}</h1>']
    if m.get("image"):
        parts.append(core.image_figure(m["image"], p["url"], p["title_ko"]))
    if (v := core.VIDEO_RE.search(m.get("video") or "")):
        src = f"https://www.youtube.com/embed/{v.group(1)}" if v.group(1) else f"https://player.vimeo.com/video/{v.group(2)}"
        parts.append(f'<div class="video"><iframe src="{src}" allowfullscreen loading="lazy"></iframe></div>')
    if p.get("summary"):
        parts.append(f'<p class="lead"><b>한 줄 요약</b> — {e(p["summary"])}</p>')
    for s in p.get("sections") or []:
        parts.append(f'<h2>{e(s.get("heading", ""))}</h2><p>{e(s.get("body", ""))}</p>')
    if p.get("insight"):
        parts.append(f'<h2>💡 에디터 코멘트</h2><blockquote>{e(p["insight"])}</blockquote>')
    faq = [f for f in p.get("faq") or [] if f.get("q")]
    if faq:
        parts.append("<h2>❓ 자주 묻는 질문</h2>" + "".join(
            f'<details><summary>Q. {e(f["q"])}</summary><p>{e(f.get("a", ""))}</p></details>' for f in faq))
    if related:
        parts.append("<h2>📚 함께 보면 좋은 글</h2><ul>" + "".join(
            f'<li><a href="{root}p/{r["id"]}.html">{e(r["title_ko"])}</a></li>' for r in related) + "</ul>")
    tags = "".join(f'<a>#{e(t)}</a>' for t in p.get("tags") or [])
    parts.append(f'<p class="tags">{tags}</p><hr><p>원문: <a href="{e(p["url"])}" target="_blank" rel="noopener nofollow">'
                 f'{e(p.get("title") or p["url"])}</a></p><p class="crumb">본 글은 원문을 요약·번역한 큐레이션 콘텐츠입니다.</p>')
    return "<article>" + "".join(parts) + "</article>"


# ─────────────────────────── 빌드 ───────────────────────────
def build() -> dict:
    posts = load_posts()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    (OUT / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    static = ROOT / "static"  # 검색엔진 소유확인 파일 등 그대로 복사 (예: Google Search Console html)
    if static.exists():
        shutil.copytree(static, OUT, dirs_exist_ok=True)

    by_dom: dict[str, list] = defaultdict(list)
    by_cat: dict[tuple, list] = defaultdict(list)
    for p in posts:
        by_dom[p["domain"]].append(p)
        by_cat[(p["domain"], p.get("category") or "기타")].append(p)

    # 홈: 최신 글 + 도메인별 카테고리 게시판 카드
    cards = []
    for d in core.DOMAINS:
        cats = sorted({c for (dd, c) in by_cat if dd == d}, key=lambda c: -len(by_cat[(d, c)]))
        items = "".join(f'<li><a href="{{ROOT}}{cat_url(d, c)}">{e(c)}</a> <span class="n">({len(by_cat[(d, c)])})</span></li>'
                        for c in cats[:8])
        cards.append(f'<div class="box"><h3>{DOMAIN_ICON[d]} {e(d)} <small class="n">{len(by_dom[d])}</small></h3>'
                     f'<ul>{items or "<li>준비 중</li>"}</ul><a class="more" href="{{ROOT}}{cat_url(d)}">게시판 전체 →</a></div>')
    home_head = (f'<h1>최신 글</h1><p class="desc">{e(SITE_DESC)} · 총 {len(posts)}개</p>'
                 f'<div class="grid">{"".join(cards)}</div><h1>전체 글</h1>')
    board_pages(posts, OUT, "", "전체 글", home_head, "")

    # 도메인 게시판 + 세부 카테고리 게시판
    for d in core.DOMAINS:
        cats = sorted({c for (dd, c) in by_cat if dd == d}, key=lambda c: -len(by_cat[(d, c)]))

        def tabs(active: str | None, root: str) -> str:
            t = f'<a class="{"on" if active is None else ""}" href="{root}{cat_url(d)}">전체<span class="n">{len(by_dom[d])}</span></a>'
            return '<div class="tabs">' + t + "".join(
                f'<a class="{"on" if c == active else ""}" href="{root}{cat_url(d, c)}">{e(c)}<span class="n">{len(by_cat[(d, c)])}</span></a>'
                for c in cats) + "</div>"

        board_pages(by_dom[d], OUT / cat_url(d).rstrip("/"), "../../", d,
                    f"<h1>{DOMAIN_ICON[d]} {e(d)}</h1>" + tabs(None, "{ROOT}"), d)
        for c in cats:
            folder = OUT / "c" / DOMAIN_SLUG[d] / slug(c)
            board_pages(by_cat[(d, c)], folder, "../../../", f"{d} › {c}",
                        f"<h1>{DOMAIN_ICON[d]} {e(d)} › {e(c)}</h1>" + tabs(c, "{ROOT}"), d)

    # 글 페이지
    (OUT / "p").mkdir()
    for p in posts:
        related = [r for r in by_cat[(p["domain"], p.get("category") or "기타")] if r["id"] != p["id"]][:3] or \
                  [r for r in by_dom[p["domain"]] if r["id"] != p["id"]][:3]
        (OUT / "p" / f"{p['id']}.html").write_text(
            page(f"{p['title_ko']} - {SITE_TITLE}", post_html(p, "../", related), "../", p["domain"],
                 p.get("summary") or SITE_DESC, f"{BASE_URL}/p/{p['id']}.html"), encoding="utf-8")

    # 검색 인덱스·RSS·사이트맵
    (OUT / "search.json").write_text(json.dumps(
        [{"i": p["id"], "t": p["title_ko"], "c": f'{p["domain"]} › {p.get("category") or ""}',
          "g": " ".join(p.get("tags") or [])} for p in posts], ensure_ascii=False), encoding="utf-8")
    items = "".join(f"<item><title>{e(p['title_ko'])}</title><link>{BASE_URL}/p/{p['id']}.html</link>"
                    f"<guid>{BASE_URL}/p/{p['id']}.html</guid><category>{e(p['domain'])}</category>"
                    f"<description>{e(p.get('summary') or '')}</description></item>" for p in posts[:50])
    (OUT / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                                  f"<title>{SITE_TITLE}</title><link>{BASE_URL}/</link><description>{e(SITE_DESC)}"
                                  f"</description>{items}</channel></rss>", encoding="utf-8")
    urls = [f"{BASE_URL}/"] + [f"{BASE_URL}/{cat_url(d)}" for d in core.DOMAINS] + \
           [f"{BASE_URL}/p/{p['id']}.html" for p in posts]
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/'
                                     'schemas/sitemap/0.9">' + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
                                     + "</urlset>", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    return {"posts": len(posts), "boards": len(by_cat) + len(core.DOMAINS)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="노션 글을 content/posts 로 복원")
    a = ap.parse_args()
    if a.backfill:
        print("노션 복원:", backfill_from_notion(), "개")
    print("빌드:", build())
