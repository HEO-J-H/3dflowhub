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

배포: .github/workflows/pages.yml (저장소 Settings → Pages → Source: GitHub Actions, Python 3.12)
"""
from __future__ import annotations

import argparse
import html
import json
import os
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
TOPIC_SLUG = {"업데이트·출시": "update", "튜토리얼·팁": "tutorial", "플러그인·스크립트": "plugin",
              "작품·제작 사례": "showcase", "업계 소식": "news", "연구·논문": "research", "리뷰·비교": "review"}
CONTACT_EMAIL = "hjh1014@naver.com"  # 광고·제휴 문의 연락처


def site_cfg() -> dict:
    """config.json 의 사이트 수익화/분석 설정 (대시보드 💰 탭에서 입력 → GitHub 반영)."""
    c = core._load_json(core.CONFIG_PATH, {})
    return {"goatcounter": (c.get("goatcounter_code") or "").strip(),
            "adsense": (c.get("adsense_client") or os.getenv("ADSENSE_CLIENT", "")).strip(),
            "base_url": (c.get("site_base_url") or BASE_URL).rstrip("/")}


def head_scripts() -> str:
    cfg, out = site_cfg(), []
    if re.fullmatch(r"[a-z0-9-]{2,50}", cfg["goatcounter"]):  # 방문 통계 (쿠키 없음)
        out.append(f'<script data-goatcounter="https://{cfg["goatcounter"]}.goatcounter.com/count" '
                   f'async src="//gc.zgo.at/count.js"></script>')
    if re.fullmatch(r"ca-pub-\d{10,20}", cfg["adsense"]):  # 애드센스 자동 광고 (승인 후)
        out.append(f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{cfg["adsense"]}" crossorigin="anonymous"></script>')
    return "\n".join(out)


def mail_link(subject: str = "[3dflowhub] 광고·제휴 문의") -> str:
    """스팸 수집기 대응: 주소를 HTML 엔티티로 인코딩한 mailto 링크 (브라우저에서는 정상 표시·클릭)."""
    enc = "".join(f"&#{ord(c)};" for c in CONTACT_EMAIL)
    return f'<a href="mailto:{enc}?subject={quote(subject)}">{enc}</a>'
# 도메인 주소·아이콘 (대시보드에서 추가한 분야 포함 — core.DOMAIN_META)
DOMAIN_SLUG = {d: m["slug"] for d, m in core.DOMAIN_META.items()}
DOMAIN_ICON = {d: m["icon"] for d, m in core.DOMAIN_META.items()}
e = html.escape


def rfc822(iso: str | None) -> str:
    from email.utils import format_datetime
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt)
    except ValueError:
        return format_datetime(datetime.now().astimezone())


def board_domains() -> list[str]:
    """사이트 게시판 대상: 수집 중인 분야 + 글이 남아 있는 보관 분야."""
    return list(core.DOMAINS) + [d for d in core.ARCHIVED_DOMAINS if d not in core.DOMAINS]


def slug(name: str) -> str:
    s = re.sub(r"[\s/·]+", "-", name.strip())
    s = re.sub(r"[^\w\-가-힣]", "", s)
    return s.strip("-").lower() or "etc"


SLUG_MAP: dict[tuple[str, str], str] = {}  # (도메인, 카테고리) → 폴더명 (build 시작 때 채움)


def assign_slugs(pairs) -> None:
    SLUG_MAP.clear()
    used: dict[str, set] = {}
    for d, c in sorted(pairs):
        base, n = slug(c), 1
        taken = used.setdefault(d, {"page"})  # 'page' 는 페이지네이션 폴더명 → 도구 슬러그로 쓰지 않음
        name = base
        while name.lower() in taken:  # Windows 대소문자 무시 파일시스템까지 고려
            n += 1
            name = f"{base}-{n}"
        taken.add(name.lower())
        SLUG_MAP[(d, c)] = name


def cat_url(domain: str, sub: str | None = None) -> str:
    base = f"c/{DOMAIN_SLUG.get(domain, slug(domain))}/"
    return base + (f"{quote(SLUG_MAP.get((domain, sub)) or slug(sub))}/" if sub else "")


# ─────────────────────────── 데이터 ───────────────────────────
def load_posts() -> list[dict]:
    posts = []
    for f in sorted(core.POSTS_DIR.glob("*.json")):
        p = core._load_json(f, None)
        if isinstance(p, dict) and p.get("title_ko"):
            p.setdefault("id", f.stem)
            if p.get("domain") not in core.DOMAIN_META:  # 정보가 전혀 없는 도메인만 대체 (보관 분야는 유지)
                p["domain"] = "3D DCC"
            posts.append(p)
    cur = core.curation_state()  # 대시보드 에디터 선택: 숨김은 제외, 추천은 표시
    posts = [p for p in posts if cur.get(p["id"]) != "hide"]
    for p in posts:
        p["pick"] = cur.get(p["id"]) == "pick"
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
/* 3dflowhub — Human Interface 원칙(명료함·콘텐츠 우선·깊이)을 따른 디자인 시스템 */
:root{
  --bg:#f5f5f7;--surface:#ffffff;--surface-2:#fbfbfd;--text:#1d1d1f;--text-2:#424245;--muted:#6e6e73;
  --line:rgba(0,0,0,.08);--accent:#0071e3;--accent-2:#5e5ce6;--accent-soft:rgba(0,113,227,.08);
  --glass:rgba(255,255,255,.72);--shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.06);
  --shadow-lift:0 2px 4px rgba(0,0,0,.05),0 16px 40px rgba(0,0,0,.10);
  --r-lg:20px;--r:14px;--r-sm:10px;--hero:linear-gradient(135deg,#eef4ff 0%,#f6efff 50%,#fff4ec 100%);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#000000;--surface:#1c1c1e;--surface-2:#141416;--text:#f5f5f7;--text-2:#d2d2d7;--muted:#98989d;
  --line:rgba(255,255,255,.10);--accent:#2997ff;--accent-2:#7d7aff;--accent-soft:rgba(41,151,255,.14);
  --glass:rgba(22,22,24,.72);--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);
  --shadow-lift:0 2px 4px rgba(0,0,0,.5),0 16px 40px rgba(0,0,0,.5);
  --hero:linear-gradient(135deg,#0b1a33 0%,#1a1033 50%,#2a1608 100%);
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
  font:17px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","Pretendard","Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;
  letter-spacing:-.01em;-webkit-font-smoothing:antialiased;word-break:keep-all;overflow-wrap:anywhere}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:8px}
img{display:block}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.skip{position:absolute;left:-999px;top:8px;background:var(--surface);padding:8px 14px;border-radius:10px;z-index:20}
.skip:focus{left:12px}

/* 헤더: 반투명 재질 (콘텐츠 우선) */
header{position:sticky;top:0;z-index:10;background:var(--glass);
  -webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);border-bottom:1px solid var(--line)}
.top{display:flex;align-items:center;gap:20px;height:56px}
.logo{display:flex;align-items:center;gap:10px;min-height:44px}
.logo .mark{flex:none;border-radius:8px;box-shadow:0 2px 8px rgba(94,92,230,.35);transition:transform .35s ease}
.logo:hover .mark{transform:rotate(-8deg) scale(1.06)}
.logo .word{font:800 21px/1 -apple-system,BlinkMacSystemFont,"SF Pro Display","Pretendard",system-ui,sans-serif;letter-spacing:-.04em}
.logo .w3d{background:linear-gradient(135deg,#0a84ff,#5e5ce6 55%,#bf5af2);-webkit-background-clip:text;background-clip:text;color:transparent;margin-right:1px}
.logo .wflow{color:var(--text)}.logo .whub{color:var(--muted);font-weight:600}
.logo:hover .wflow{color:var(--text)}
.topnav{display:flex;gap:4px}.topnav a{font-size:14px;color:var(--text-2);padding:10px 10px;border-radius:10px}
.topnav a:hover,.topnav a.on{color:var(--text);background:var(--accent-soft)}
.search{margin-left:auto;flex:0 1 280px;position:relative}
.search input{width:100%;height:36px;padding:0 14px 0 34px;border:1px solid var(--line);border-radius:10px;
  background:var(--surface-2);color:var(--text);font-size:15px}
.search:before{content:"⌕";position:absolute;left:12px;top:50%;transform:translateY(-52%);color:var(--muted);font-size:17px}
nav.domains{display:flex;gap:8px;overflow-x:auto;padding:8px 0 12px;scrollbar-width:none}nav.domains::-webkit-scrollbar{display:none}
nav.domains a{display:inline-flex;align-items:center;gap:6px;min-height:36px;padding:0 14px;border-radius:999px;white-space:nowrap;
  font-size:14px;font-weight:500;background:var(--surface);border:1px solid var(--line)}
nav.domains a.on{background:var(--text);color:var(--bg);border-color:var(--text)}

/* 타이포 위계 */
h1{font-size:34px;line-height:1.15;letter-spacing:-.03em;margin:40px 0 8px;font-weight:700}
h2.sec{font-size:24px;letter-spacing:-.02em;margin:48px 0 16px;display:flex;align-items:baseline;justify-content:space-between}
h2.sec a{font-size:15px;font-weight:500;color:var(--accent)}
.desc{color:var(--muted);margin:0 0 16px;font-size:17px}

/* 히어로 */
.hero{margin:24px 0 8px;padding:56px 40px;border-radius:28px;background:var(--hero);position:relative;overflow:hidden}
.hero h1{font-size:clamp(32px,5vw,52px);margin:0 0 12px}
.hero p{font-size:clamp(17px,2vw,21px);color:var(--text-2);max-width:640px;margin:0 0 24px}
.hero .stats{display:flex;gap:28px;flex-wrap:wrap;color:var(--muted);font-size:15px}
.hero .stats b{display:block;font-size:28px;color:var(--text);letter-spacing:-.02em}
.btn{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 20px;border-radius:999px;font-weight:600;font-size:16px}
.btn.primary{background:var(--accent);color:#fff}.btn.primary:hover{color:#fff;filter:brightness(1.08)}
.btn.ghost{color:var(--accent)}.hero .actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px}

/* 카드 */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:20px}
.card{display:flex;flex-direction:column;background:var(--surface);border-radius:var(--r-lg);overflow:hidden;
  box-shadow:var(--shadow);transition:transform .25s ease,box-shadow .25s ease}
.card:hover{transform:translateY(-3px);box-shadow:var(--shadow-lift);color:inherit}
.card .img{aspect-ratio:16/9;background:var(--accent-soft);overflow:hidden}
.card .img img{width:100%;height:100%;object-fit:cover}
.card .img.ph{display:flex;align-items:center;justify-content:center;font-size:40px;
  background:linear-gradient(135deg,var(--accent-soft),rgba(94,92,230,.12))}
.card .body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:6px;flex:1}
.card .kicker{font-size:12px;font-weight:600;letter-spacing:.02em;color:var(--accent);text-transform:uppercase}
.card .t{font-size:18px;font-weight:600;line-height:1.35;letter-spacing:-.015em}
.card .s{color:var(--muted);font-size:14px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .meta{margin-top:auto;color:var(--muted);font-size:13px;padding-top:6px}
.cards.lead-grid{grid-template-columns:2fr 1fr 1fr}.cards.lead-grid .card:first-child{grid-row:span 2}
.cards.lead-grid .card:first-child .t{font-size:24px}
.rank{counter-reset:r;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:4px 24px;
  background:var(--surface);border-radius:var(--r-lg);padding:8px 20px;box-shadow:var(--shadow)}
.rank a{counter-increment:r;display:flex;gap:14px;align-items:center;min-height:64px;padding:10px 0;border-bottom:1px solid var(--line)}
.rank a:before{content:counter(r);font-size:22px;font-weight:700;color:var(--accent);width:24px;text-align:center;flex:none}
.rank .t{font-weight:600;font-size:15px;line-height:1.35}.rank .k{color:var(--muted);font-size:12px}

/* 도메인 타일 */
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.tile{background:var(--surface);border-radius:var(--r-lg);padding:22px;box-shadow:var(--shadow)}
.tile .ic{font-size:32px}.tile h3{margin:8px 0 4px;font-size:20px;letter-spacing:-.02em}
.tile .n{color:var(--muted);font-size:14px}.tile .tools{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 4px}
.tile .tools a{font-size:13px;padding:6px 10px;border-radius:8px;background:var(--surface-2);border:1px solid var(--line)}

/* 분야 카드 (처음 디자인의 목록형 카드) */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}
.box{background:var(--surface);border-radius:var(--r-lg);padding:20px 22px;box-shadow:var(--shadow);display:flex;flex-direction:column}
.box h3{margin:0 0 12px;font-size:20px;letter-spacing:-.02em;display:flex;align-items:center;gap:8px}
.box h3 small{margin-left:auto;font-size:14px;font-weight:500;color:var(--muted)}
.box ul{list-style:none;margin:0;padding:0}.box li{display:flex;justify-content:space-between;align-items:center;
  min-height:36px;border-bottom:1px solid var(--line);font-size:15px}.box li:last-child{border-bottom:0}
.box li .n{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.box .more{margin-top:12px;font-size:14px;font-weight:600;color:var(--accent)}
.links{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.links a{background:var(--surface);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:4px}
.links b{font-size:16px}.links span{color:var(--muted);font-size:14px}
nav.domains .mob,nav.domains .sep{display:none}

/* 탭·칩·게시판 목록 */
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}
.tabs a{display:inline-flex;align-items:center;min-height:36px;font-size:14px;padding:0 14px;border-radius:999px;
  background:var(--surface);border:1px solid var(--line);font-weight:500}
.tabs a.on{background:var(--accent);border-color:var(--accent);color:#fff}
.chips{margin-top:-6px}.chips a{min-height:32px;font-size:13px;background:transparent}
.chips a.on{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.tabs .n{opacity:.6;margin-left:6px;font-variant-numeric:tabular-nums}
.board{background:var(--surface);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--shadow)}
.row{display:grid;grid-template-columns:112px 1fr auto;gap:18px;align-items:center;padding:14px 18px;border-top:1px solid var(--line);min-height:88px}
.row:first-child{border-top:0}.row:hover{background:var(--surface-2)}
.row img,.row .ph{width:112px;height:63px;object-fit:cover;border-radius:var(--r-sm);background:var(--accent-soft)}
.row .t{font-weight:600;line-height:1.4}.row .s{color:var(--muted);font-size:14px;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.row .side{text-align:right;display:flex;flex-direction:column;gap:2px;align-items:flex-end}
.badge{font-size:12px;font-weight:600;color:var(--accent);background:var(--accent-soft);padding:3px 8px;border-radius:6px;white-space:nowrap}
.date{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.pager{display:flex;gap:6px;justify-content:center;margin:28px 0}
.pager a{min-width:40px;min-height:40px;display:inline-flex;align-items:center;justify-content:center;border-radius:10px;background:var(--surface);border:1px solid var(--line)}
.pager a.on{background:var(--accent);color:#fff;border-color:var(--accent)}

/* 글 페이지: 읽기 폭 제한 */
article{background:var(--surface);border-radius:var(--r-lg);padding:clamp(22px,4vw,48px);margin:28px auto;max-width:780px;box-shadow:var(--shadow)}
article h1{font-size:clamp(28px,4vw,40px);margin:8px 0 20px}
article h2{font-size:22px;letter-spacing:-.02em;margin:36px 0 10px}
article p{color:var(--text-2);font-size:18px;line-height:1.75}
article img{max-width:100%;border-radius:var(--r)}
.crumb{font-size:14px;color:var(--muted)}.crumb a{color:var(--accent)}
.lead{background:var(--accent-soft);border-radius:var(--r);padding:16px 20px;color:var(--text)!important}
.video{position:relative;padding-top:56.25%;margin:20px 0}.video iframe{position:absolute;inset:0;width:100%;height:100%;border:0;border-radius:var(--r)}
blockquote{margin:0;padding:16px 20px;background:var(--surface-2);border:1px solid var(--line);border-left:4px solid var(--accent-2);border-radius:var(--r)}
figure{margin:0 0 20px}figcaption{color:var(--muted);font-size:13px;text-align:center;margin-top:8px}
.tags a{display:inline-block;font-size:13px;color:var(--muted);margin:0 8px 6px 0}
details{border:1px solid var(--line);border-radius:var(--r);padding:12px 16px;margin:10px 0;background:var(--surface-2)}
summary{cursor:pointer;font-weight:600;min-height:28px}
.aside{max-width:780px;margin:0 auto 40px}

/* 문서형 페이지 (소개·주간 요약) */
.doc{max-width:780px;margin:0 auto}
.doc .pill{display:inline-block;font-size:13px;font-weight:600;color:var(--accent);background:var(--accent-soft);padding:4px 10px;border-radius:999px}
.steps{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin:16px 0}
.step{background:var(--surface);border-radius:var(--r);padding:18px;box-shadow:var(--shadow)}
.step b{display:block;font-size:17px;margin:6px 0 4px}.step span{color:var(--muted);font-size:15px}

footer{color:var(--muted);font-size:13px;padding:48px 0 56px;border-top:1px solid var(--line);margin-top:64px}
footer .cols{display:flex;flex-wrap:wrap;gap:12px 28px;margin-bottom:12px}footer a{color:var(--text-2)}

@media (max-width:820px){.cards.lead-grid{grid-template-columns:1fr}.cards.lead-grid .card:first-child{grid-row:auto}.topnav{display:none}
  nav.domains .mob{display:inline-flex}nav.domains .sep{display:block;flex:none;width:1px;background:var(--line);margin:6px 2px}}
@media (max-width:640px){
  body{font-size:16px}.wrap{padding:0 16px}.hero{padding:36px 22px;border-radius:22px}
  .row{grid-template-columns:84px 1fr;gap:12px}.row img,.row .ph{width:84px;height:56px}.row .side{display:none}
  .search{flex-basis:150px}h1{font-size:28px}article p{font-size:17px}
  .hero h1{font-size:30px}.hero h1 br{display:none}.hero .stats{gap:18px}.hero .stats b{font-size:24px}
  nav.domains a,.tabs a{min-height:44px}.btn.ghost{padding:0 4px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}

/* 기초 가이드 (영상 우선) */
.yt{position:relative;display:block;width:100%;aspect-ratio:16/9;border:0;padding:0;border-radius:18px;overflow:hidden;
  background:#000 center/cover no-repeat;cursor:pointer}
.yt::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 55%,rgba(0,0,0,.55))}
.yt .play{position:absolute;left:50%;top:50%;width:68px;height:68px;margin:-34px 0 0 -34px;border-radius:50%;
  background:rgba(255,255,255,.92);z-index:1;box-shadow:0 8px 24px rgba(0,0,0,.3)}
.yt .play::before{content:"";position:absolute;left:27px;top:21px;border-left:20px solid #111;border-top:13px solid transparent;
  border-bottom:13px solid transparent}
.yt .cap{position:absolute;left:16px;right:16px;bottom:12px;z-index:1;color:#fff;font-size:14px;text-align:left;
  text-shadow:0 1px 3px rgba(0,0,0,.6)}
.ytw{position:relative;width:100%;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:#000}
.ytw iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
.vids{display:grid;gap:14px;margin:18px 0}.vids.two{grid-template-columns:1fr 1fr}
@media (max-width:720px){.vids.two{grid-template-columns:1fr}}
.guide h2{font-size:21px;margin:30px 0 10px}
.steps{counter-reset:s;list-style:none;padding:0;margin:0;display:grid;gap:8px}
.steps li{counter-increment:s;position:relative;padding:12px 14px 12px 50px;background:var(--surface);border:1px solid var(--line);
  border-radius:14px}
.steps li::before{content:counter(s);position:absolute;left:14px;top:11px;width:24px;height:24px;border-radius:50%;
  background:var(--accent);color:#fff;font-size:13px;font-weight:700;display:grid;place-items:center}
.params{width:100%;border-collapse:separate;border-spacing:0;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;overflow:hidden}
.params th,.params td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}
.params tr:last-child td{border-bottom:0}.params th{font-size:13px;color:var(--muted);font-weight:600}
.params code{font-weight:600;color:var(--text)}
.ex{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.ex .box{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px 16px}
.ex .box h3{font-size:16px;margin:0 0 6px}.ex ol{margin:0;padding-left:20px}
.warn li{margin:4px 0}
.gcards{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.gcard{background:var(--surface);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column}
.gcard .th{aspect-ratio:16/9;background:var(--accent-soft) center/cover no-repeat;position:relative}
.gcard .th.v::after{content:"▶";position:absolute;right:10px;bottom:8px;background:rgba(0,0,0,.65);color:#fff;font-size:11px;
  padding:3px 8px;border-radius:99px}
.gcard .b{padding:12px 14px}.gcard .k{font-size:12px;color:var(--accent);font-weight:600}
.gcard .t{display:block;font-weight:600;margin:3px 0 4px;line-height:1.35}.gcard .s{font-size:13px;color:var(--muted)}
"""

LOGO_SVG = """<svg class="mark" viewBox="0 0 64 64" width="30" height="30" aria-hidden="true">
<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a84ff"/>
<stop offset=".55" stop-color="#5e5ce6"/><stop offset="1" stop-color="#bf5af2"/></linearGradient></defs>
<rect width="64" height="64" rx="15" fill="url(#lg)"/>
<ellipse class="orbit" cx="32" cy="33" rx="25" ry="10" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="2.2" transform="rotate(-22 32 33)"/>
<path d="M32 13 L48 22 L32 31 L16 22 Z" fill="#fff"/><path d="M16 22 L32 31 L32 50 L16 41 Z" fill="#fff" fill-opacity=".72"/>
<path d="M48 22 L32 31 L32 50 L48 41 Z" fill="#fff" fill-opacity=".45"/><circle cx="54.5" cy="22.5" r="3" fill="#fff"/></svg>"""

SEARCH_JS = """
const q=document.getElementById('q');let idx=null;
const h=s=>String(s).replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');
q&&q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();const box=document.getElementById('results');
if(!v){box.innerHTML='';box.hidden=true;return}
idx=idx||await (await fetch(ROOT+'search.json')).json();
const hits=idx.filter(p=>(p.t+' '+p.c+' '+p.g).toLowerCase().includes(v)).slice(0,30);
box.hidden=false;box.innerHTML=hits.length?hits.map(p=>`<a class="row" href="${ROOT}p/${encodeURIComponent(p.i)}.html"><span class="ph"></span><span><span class="t">${h(p.t)}</span><br><span class="s">${h(p.c)}</span></span><span></span></a>`).join(''):'<div class="row">검색 결과 없음</div>'});
"""


def page(title: str, body: str, root: str, domain_on: str = "", desc: str = SITE_DESC, canonical: str = "",
         extra_head: str = "") -> str:
    nav = "".join(f'<a href="{root}{cat_url(d)}" class="{"on" if d == domain_on else ""}">{e(DOMAIN_ICON[d])} {e(d)}</a>'
                  for d in board_domains())
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc[:150])}">
{f'<link rel="canonical" href="{e(canonical)}">' if canonical else ''}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc[:150])}">
<meta property="og:site_name" content="{SITE_TITLE}"><meta name="twitter:card" content="summary_large_image">
{extra_head}
{head_scripts()}
<link rel="alternate" type="application/rss+xml" title="{SITE_TITLE}" href="{root}feed.xml">
<meta name="theme-color" content="#f5f5f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}assets/style.css"></head><body>
<a class="skip" href="#main">본문으로 건너뛰기</a>
<header><div class="wrap"><div class="top"><a class="logo" href="{root}" aria-label="{SITE_TITLE} 홈">{LOGO_SVG}<span class="word" aria-hidden="true"><span class="w3d">3d</span><span class="wflow">flow</span><span class="whub">hub</span></span></a>
<nav class="topnav" aria-label="사이트"><a href="{root}learn/">기초 가이드</a><a href="{root}guide/">도구별 정리</a><a href="{root}weekly/">주간 요약</a><a href="{root}about/">소개</a><a href="{root}contact/">문의</a></nav>
<div class="search" role="search"><input id="q" type="search" placeholder="Blender, 언리얼, 가우시안…" aria-label="사이트 검색"></div></div>
<nav class="domains" aria-label="분야"><a href="{root}" class="{"on" if not domain_on else ""}">전체</a>{nav}<span class="sep mob" aria-hidden="true"></span><a class="mob" href="{root}learn/">📚 기초 가이드</a><a class="mob" href="{root}guide/">🧭 도구별 정리</a><a class="mob" href="{root}weekly/">🗓️ 주간 요약</a><a class="mob" href="{root}about/">📘 소개</a><a class="mob" href="{root}contact/">✉️ 문의</a></nav></div></header>
<main class="wrap" id="main"><div id="results" class="board" hidden style="margin-top:20px" aria-live="polite"></div>{body}</main>
<footer><div class="wrap"><div class="cols"><a href="{root}about/">소개</a><a href="{root}weekly/">주간 요약</a>
<a href="{root}feed.xml">RSS 구독</a><a href="{root}contact/">문의</a><a href="{root}privacy/">개인정보처리방침</a></div>
© {datetime.now():%Y} {SITE_TITLE} · 3D를 배우고 나누는 사람들을 위한 큐레이션 · 원문 저작권은 각 출처에 있습니다 · {mail_link()}</div></footer>
<script>const ROOT="{root}";{SEARCH_JS}</script></body></html>"""


def row(p: dict, root: str) -> str:
    img = (p.get("media") or {}).get("image")
    thumb = f'<img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if img else '<span class="ph"></span>'
    return (f'<a class="row" href="{root}p/{p["id"]}.html">{thumb}<span><span class="t">{e(p["title_ko"])}</span><br>'
            f'<span class="s">{e(p.get("summary") or "")}</span></span>'
            f'<span class="side"><span class="badge">{e(p.get("category") or "기타")}'
            f'{" · " + e(p["topic"]) if p.get("topic") else ""}</span>'
            f'<span class="date">{(p.get("collected_at") or "")[:10]}</span></span></a>')


MIN_INDEXABLE = 3  # 글이 이보다 적은 하위 게시판은 noindex (얇은 페이지가 사이트 품질 평가를 떨어뜨리지 않도록)


def card(p: dict, root: str) -> str:
    img = (p.get("media") or {}).get("image")
    pic = (f'<div class="img"><img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer"></div>' if img
           else f'<div class="img ph" aria-hidden="true">{e(DOMAIN_ICON.get(p["domain"], "🧊"))}</div>')
    return (f'<a class="card" href="{root}p/{p["id"]}.html">{pic}<div class="body">'
            f'<span class="kicker">{e(p.get("category") or p["domain"])}{" · " + e(p["topic"]) if p.get("topic") else ""}</span>'
            f'<span class="t">{e(p["title_ko"])}</span><span class="s">{e(p.get("summary") or "")}</span>'
            f'<span class="meta">{(p.get("collected_at") or "")[:10]}</span></div></a>')


def page_views() -> dict[str, int]:
    """GitHub Pages 글별 조회수 (GoatCounter → memory/performance.json)."""
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
    return {k: v.get("views", 0) for k, v in ((perf.get("pages") or {}).get("posts") or {}).items()}


def popular(posts: list[dict], n: int = 8, days: int = 30) -> list[dict]:
    """많이 본 글: 최근 N일 조회수 순. 조회 데이터가 부족하면 이미지·요약이 있는 최신 글로 채움."""
    views = page_views()
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [p for p in posts if (p.get("collected_at") or "") >= cutoff] or posts
    ranked = sorted([p for p in recent if views.get(p["id"]) or p.get("pick")],
                    key=lambda p: -(views.get(p["id"], 0) + (20 if p.get("pick") else 0)))  # 추천 가산
    filler = [p for p in recent if p not in ranked and (p.get("media") or {}).get("image")]
    return (ranked + filler + [p for p in recent if p not in ranked and p not in filler])[:n]


def iso_week(p: dict) -> str:
    try:
        y, w, _ = datetime.fromisoformat((p.get("collected_at") or "")[:10]).isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return ""


def board_pages(posts: list[dict], out_dir: Path, root: str, title: str, header: str, domain_on: str,
                indexable: bool = True, header_more: str | None = None) -> None:
    """게시판 목록 (페이지네이션: index.html, page/2/ ...)."""
    pages = [posts[i:i + PAGE_SIZE] for i in range(0, max(len(posts), 1), PAGE_SIZE)] or [[]]
    for n, chunk in enumerate(pages, 1):
        r = root + ("../../" if n > 1 else "")
        pager = "".join(f'<a class="{"on" if k == n else ""}" href="{r}{out_dir.relative_to(OUT).as_posix()}/'
                        f'{"" if k == 1 else f"page/{k}/"}">{k}</a>' for k in range(1, len(pages) + 1)) \
            if len(pages) > 1 else ""
        head = header if n == 1 or header_more is None else header_more
        body = head.replace("{ROOT}", r) + '<div class="board">' + ("".join(row(p, r) for p in chunk)
                                                                       or '<div class="row">아직 글이 없습니다.</div>') \
            + f'</div><div class="pager">{pager}</div>'
        d = out_dir if n == 1 else out_dir / "page" / str(n)
        d.mkdir(parents=True, exist_ok=True)
        robots = "" if indexable else '<meta name="robots" content="noindex,follow">'
        (d / "index.html").write_text(page(f"{title} - {SITE_TITLE}", body, r, domain_on, extra_head=robots),
                                      encoding="utf-8")


def build_about(posts: list[dict], by_dom: dict, by_cat: dict) -> None:
    d = OUT / "about"
    d.mkdir(exist_ok=True)
    domains = "".join(
        f'<div class="step"><span aria-hidden="true" style="font-size:28px">{e(DOMAIN_ICON[x])}</span><b>{e(x)}</b>'
        f'<span>{e(core.DOMAIN_META.get(x, {}).get("about", ""))}</span></div>' for x in board_domains())
    body = f"""<div class="doc"><h1>3D를 함께 배우고 나누는 곳</h1>
<p class="desc">3dflowhub는 3D·게임 엔진·VFX·AI 3D 분야의 전 세계 소식과 학습 자료를 매일 모아 한국어로 정리하는 큐레이션 아카이브입니다.</p>
<h2 class="sec">왜 만들었나요</h2>
<p>좋은 3D 자료는 대부분 영어로, 여러 사이트·커뮤니티·논문에 흩어져 있습니다. 업데이트 하나, 튜토리얼 하나를 찾느라 시간을 쓰기보다
<b>매일 한곳에서 흐름을 따라가고</b>, 관심 도구를 깊게 공부하고, 다른 분야까지 시야를 넓힐 수 있도록 이곳을 만들었습니다.</p>
<h2 class="sec">이렇게 활용해 보세요</h2>
<div class="steps">
<div class="step"><span class="pill">공부</span><b>도구별 게시판</b><span>Blender, 3ds Max, 언리얼처럼 쓰는 도구를 골라 <em>튜토리얼·팁</em>만 모아 보세요.</span></div>
<div class="step"><span class="pill">흐름</span><b>주간 요약</b><span>한 주의 핵심만 추려 둔 <a href="../weekly/">주간 요약</a>으로 업계 변화를 놓치지 마세요.</span></div>
<div class="step"><span class="pill">확장</span><b>다른 분야 탐색</b><span>모델러라면 AI 3D를, 게임 개발자라면 VFX를 — 옆 분야에서 새로운 아이디어를 얻으세요.</span></div>
<div class="step"><span class="pill">깊이</span><b>원문으로 이어가기</b><span>모든 글에 원문 링크가 있습니다. 요약으로 감을 잡고 원문에서 깊게 파고드세요.</span></div>
</div>
<h2 class="sec">다루는 분야</h2><div class="steps">{domains}</div>
<h2 class="sec">어떻게 정리되나요</h2>
<p>공식 블로그·전문 매체·커뮤니티·논문(arXiv)에서 새 소식을 수집하고, AI가 핵심을 한국어로 요약해 <b>분야 › 도구 › 콘텐츠 유형</b>으로 분류합니다.
글마다 <b>에디터 코멘트</b>로 실무에서 어떻게 활용할지 덧붙이고, 주제와 무관한 글은 자동으로 걸러냅니다.
요약은 이해를 돕기 위한 것이므로, 정확한 내용과 저작권은 항상 <b>원문</b>을 기준으로 해 주세요.</p>
<div class="steps"><div class="step"><b>{len(posts)}</b><span>지금까지 정리된 글</span></div>
<div class="step"><b>{len(by_cat)}</b><span>도구·주제 게시판</span></div>
<div class="step"><b>매일</b><span>자동으로 새 소식 업데이트</span></div></div>
<h2 class="sec">함께해요</h2>
<p>소개하고 싶은 자료, 잘못된 요약, 원문 저작권 관련 요청은 언제든 {mail_link('[3dflowhub] 자료 제보·의견')} 으로 보내 주세요.
<a href="../feed.xml">RSS</a>로 구독하면 새 글을 바로 받아볼 수 있습니다.</p></div>"""
    (d / "index.html").write_text(page(f"소개 - {SITE_TITLE}", body, "../", desc="3D를 함께 배우고 나누는 큐레이션 아카이브, 3dflowhub 소개"),
                                  encoding="utf-8")


def load_roundups(posts: list[dict]) -> list[dict]:
    """content/roundups/*.json (evolve 가 주 1회 생성) → 사이트에 있는 도구만, 최신순."""
    have = {(p["domain"], p.get("category") or "기타") for p in posts}
    out = [r for f in core.ROUNDUP_DIR.glob("*.json") if (r := core._load_json(f, None))
           and isinstance(r, dict) and r.get("intro") and (r.get("domain"), r.get("tool")) in have]
    return sorted(out, key=lambda r: r.get("at", ""), reverse=True)


def guide_url(domain: str, tool: str) -> str:
    return "guide/" + cat_url(domain, tool)[2:]  # c/<분야>/<도구>/ → guide/<분야>/<도구>/


def build_guides(posts: list[dict], roundups: list[dict]) -> None:
    """도구별 정리: 이번 달 흐름 · 핵심 포인트 · 먼저 볼 글 · 유형별 전체 목록 (개별 요약을 묶은 2차 콘텐츠)."""
    root_dir = OUT / "guide"
    root_dir.mkdir(exist_ok=True)
    by_id = {p["id"]: p for p in posts}
    for r in roundups:
        d, t = r["domain"], r["tool"]
        folder = OUT / guide_url(d, t).rstrip("/")
        folder.mkdir(parents=True, exist_ok=True)
        root = "../../../"
        ps = [by_id[i] for i in r.get("post_ids", []) if i in by_id]
        picks = [by_id[i] for i in r.get("picks", []) if i in by_id]
        why = r.get("why", {})
        pick_html = "".join(
            f'<a href="{root}p/{q["id"]}.html"><span><span class="t">{e(q["title_ko"])}</span><br>'
            f'<span class="k">{e(why.get(q["id"], q.get("topic") or ""))}</span></span></a>' for q in picks)
        groups = []
        for topic in TOPIC_SLUG:
            tp = [q for q in ps if q.get("topic") == topic]
            if tp:
                groups.append(f'<h2 class="sec">{e(topic)} <small class="n">{len(tp)}</small></h2>'
                              f'<div class="cards">{"".join(card(q, root) for q in tp[:6])}</div>')
        rest = [q for q in ps if q.get("topic") not in TOPIC_SLUG]
        if rest:
            groups.append(f'<h2 class="sec">기타</h2><div class="cards">{"".join(card(q, root) for q in rest[:6])}</div>')
        body = (f'<div class="doc"><p class="crumb"><a href="{root}guide/">도구별 정리</a> › '
                f'<a href="{root}{cat_url(d)}">{e(d)}</a> › <a href="{root}{cat_url(d, t)}">{e(t)} 게시판</a></p>'
                f'<span class="pill">{e(r.get("at", "")[:10])} 업데이트</span><h1>{e(r["title"])}</h1>'
                f'<p class="lead">{e(r["intro"])}</p>'
                + (f'<h2>핵심 포인트</h2><ul>{"".join(f"<li>{e(x)}</li>" for x in r.get("points", []))}</ul>'
                   if r.get("points") else "")
                + '</div>'
                + (f'<h2 class="sec">먼저 읽어 볼 글</h2><div class="rank">{pick_html}</div>' if pick_html else "")
                + "".join(groups)
                + f'<p class="crumb"><a href="{root}{cat_url(d, t)}">{e(t)} 게시판 전체 보기 →</a></p>')
        (folder / "index.html").write_text(
            page(f"{r['title']} - {SITE_TITLE}", body, root, domain_on=d, desc=r["intro"],
                 canonical=f"{BASE_URL}/{guide_url(d, t)}"), encoding="utf-8")
    items = "".join(
        f'<a href="{guide_url(r["domain"], r["tool"])[6:]}"><span><span class="t">{e(r["title"])}</span><br>'
        f'<span class="k">{e(r["domain"])} › {e(r["tool"])} · {e(r.get("at", "")[:10])}</span></span></a>'
        for r in roundups)
    body = ('<div class="doc"><h1>도구별 정리</h1><p class="desc">도구마다 최근 한 달 소식을 묶어 흐름과 핵심, '
            '먼저 읽을 글을 정리합니다. 매주 자동으로 갱신됩니다.</p></div>'
            + f'<div class="rank">{items or "<p>준비 중입니다 — 글이 충분히 쌓인 도구부터 차례로 정리됩니다.</p>"}</div>')
    (root_dir / "index.html").write_text(page(f"도구별 정리 - {SITE_TITLE}", body, "../"), encoding="utf-8")


YT_JS = """<script>document.querySelectorAll('.yt').forEach(b=>b.addEventListener('click',()=>{
const f=document.createElement('iframe');f.src='https://www.youtube-nocookie.com/embed/'+b.dataset.id+'?autoplay=1&rel=0';
f.allow='accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture';f.allowFullscreen=true;
f.title=b.getAttribute('aria-label');
// 버튼 안에 플레이어를 넣으면 클릭이 버튼에 가로채이고 썸네일 덮개가 위를 막음 → 버튼을 일반 상자로 교체
const w=document.createElement('div');w.className='ytw';w.appendChild(f);b.replaceWith(w);f.focus();},{once:true}))</script>"""


def yt_facade(v: dict) -> str:
    """가벼운 유튜브 파사드: 썸네일만 먼저, 누르면 그때 플레이어 로드 (페이지 속도·쿠키 최소화)."""
    return (f'<button class="yt" data-id="{e(v["id"])}" aria-label="영상 재생: {e(v["title"])}" '
            f'style="background-image:url(https://i.ytimg.com/vi/{e(v["id"])}/hqdefault.jpg)">'
            f'<span class="play" aria-hidden="true"></span><span class="cap">▶ {e(v["title"])} · {e(v["author"])}</span></button>')


def learn_url(g: dict) -> str:
    return f"learn/{g['id']}/"


def guide_card(g: dict, root: str) -> str:
    v = (g.get("videos") or [None])[0]
    th = (f'<div class="th v" style="background-image:url(https://i.ytimg.com/vi/{e(v["id"])}/mqdefault.jpg)"></div>' if v
          else f'<div class="th" aria-hidden="true"></div>')
    return (f'<a class="gcard" href="{root}{learn_url(g)}">{th}<div class="b"><span class="k">{e(g["tool"])} · {e(g["group"])}</span>'
            f'<span class="t">{e(g["title"])}</span><span class="s">{e(g.get("summary", "")[:70])}</span></div></a>')


def build_learn(guides_: list[dict]) -> None:
    """기초 가이드: 도구별 기본 기능(모디파이어·메뉴·노드)을 영상 + 단계별 사용법으로."""
    root_dir = OUT / "learn"
    root_dir.mkdir(exist_ok=True)
    for g in guides_:
        folder = root_dir / g["id"]
        folder.mkdir(exist_ok=True)
        root = "../../"
        vids = g.get("videos") or []
        steps = "".join(f"<li>{e(x)}</li>" for x in g["steps"])
        params = "".join(f'<tr><td><code>{e(x["name"])}</code></td><td>{e(x["desc"])}</td></tr>' for x in g.get("params", []))
        exs = "".join(f'<div class="box"><h3>{e(x["title"])}</h3><ol>{"".join(f"<li>{e(t)}</li>" for t in x["steps"])}</ol></div>'
                      for x in g.get("examples", []))
        same = [o for o in guides_ if o["tool"] == g["tool"] and o["id"] != g["id"]][:4]
        how_to = {"@context": "https://schema.org", "@type": "HowTo", "name": g["title"], "description": g.get("summary", ""),
                  "inLanguage": "ko", "step": [{"@type": "HowToStep", "position": i + 1, "text": t} for i, t in enumerate(g["steps"])]}
        if vids:
            how_to["video"] = {"@type": "VideoObject", "name": vids[0]["title"], "embedUrl": f"https://www.youtube.com/embed/{vids[0]['id']}",
                               "thumbnailUrl": f"https://i.ytimg.com/vi/{vids[0]['id']}/hqdefault.jpg",
                               "uploadDate": g.get("at", "")[:10], "description": g.get("summary", "")}
        body = (
            f'<article class="doc guide"><p class="crumb"><a href="{root}learn/">기초 가이드</a> › {e(g["tool"])} › {e(g["group"])}</p>'
            f'<h1>{e(g["title"])}</h1><p class="lead">{e(g.get("summary", ""))}</p>'
            + (f'<div class="vids{" two" if len(vids) > 1 else ""}">{"".join(yt_facade(v) for v in vids)}</div>' if vids else "")
            + (f'<h2>이럴 때 씁니다</h2><ul>{"".join(f"<li>{e(x)}</li>" for x in g.get("when", []))}</ul>' if g.get("when") else "")
            + f'<h2>따라 하기</h2><ol class="steps">{steps}</ol>'
            + (f'<h2>주요 옵션</h2><table class="params"><thead><tr><th>옵션</th><th>효과</th></tr></thead><tbody>{params}</tbody></table>'
               if params else "")
            + (f'<h2>활용 예시</h2><div class="ex">{exs}</div>' if exs else "")
            + (f'<h2>자주 하는 실수</h2><ul class="warn">{"".join(f"<li>{e(x)}</li>" for x in g.get("mistakes", []))}</ul>'
               if g.get("mistakes") else "")
            + (f'<p class="crumb">함께 알아두면 좋은 기능: {e(", ".join(g["related"]))}</p>' if g.get("related") else "")
            + f'<p class="crumb">📖 <a href="{e(g["doc"])}" target="_blank" rel="noopener">{e(g["tool"])} 공식 문서에서 자세히 보기</a>'
            + (" · 영상: " + ", ".join(f'<a href="https://www.youtube.com/watch?v={e(v["id"])}" target="_blank" rel="noopener">'
                                       f'{e(v["author"])}</a>' for v in vids) if vids else "")
            + "</p></article>"
            + (f'<h2 class="sec">{e(g["tool"])} 기초 더 보기</h2><div class="gcards">{"".join(guide_card(o, root) for o in same)}</div>'
               if same else "")
            + YT_JS)
        head = f'<script type="application/ld+json">{json.dumps(how_to, ensure_ascii=False)}</script>'
        (folder / "index.html").write_text(
            page(f"{g['title']} | {g['tool']} 기초 - {SITE_TITLE}", body, root, desc=g.get("summary", ""),
                 canonical=f"{BASE_URL}/{learn_url(g)}", extra_head=head), encoding="utf-8")
    tools: dict[str, list] = defaultdict(list)
    for g in guides_:
        tools[g["tool"]].append(g)
    nav = "".join(f'<a href="#{e(slug(t))}">{e(t)}<span class="n">{len(gs)}</span></a>' for t, gs in tools.items())
    secs = "".join(f'<h2 class="sec" id="{e(slug(t))}">{e(t)}</h2><div class="gcards">{"".join(guide_card(g, "../") for g in gs)}</div>'
                   for t, gs in tools.items())
    body = ('<div class="doc"><h1>기초 가이드</h1><p class="desc">모디파이어·메뉴·패널·노드 같은 기본 기능을 '
            '<b>영상</b>과 <b>따라 하기 단계</b>, <b>활용 예시</b>로 정리합니다. 새 소식과 달리 언제 봐도 유효한 레퍼런스예요.</p></div>'
            + (f'<div class="tabs chips">{nav}</div>{secs}' if guides_ else "<p>준비 중입니다 — 매일 몇 개씩 추가됩니다.</p>"))
    (root_dir / "index.html").write_text(page(f"기초 가이드 - {SITE_TITLE}", body, "../",
                                              desc="3ds Max·Blender·Houdini·Unreal 기본 기능을 영상과 단계별 사용법으로"),
                                         encoding="utf-8")


def build_weekly(posts: list[dict]) -> None:
    """주간 요약: ISO 주차별로 분야·도구·유형 통계와 핵심 글을 정리 (조회수 → 이미지 → 최신 순)."""
    root_dir = OUT / "weekly"
    root_dir.mkdir(exist_ok=True)
    weeks: dict[str, list] = defaultdict(list)
    for p in posts:
        if (w := iso_week(p)):
            weeks[w].append(p)
    order = sorted(weeks, reverse=True)
    views = page_views()
    for i, w in enumerate(order):
        ps = weeks[w]
        y, n = w.split("-W")
        start = datetime.fromisocalendar(int(y), int(n), 1)
        end = datetime.fromisocalendar(int(y), int(n), 7)
        tools = defaultdict(int)
        for p in ps:
            tools[(p["domain"], p.get("category") or "기타")] += 1
        top_tools = ", ".join(f"{c}({k})" for (_, c), k in sorted(tools.items(), key=lambda kv: -kv[1])[:5])
        sections = []
        for d in board_domains():
            dps = sorted([p for p in ps if p["domain"] == d],
                         key=lambda p: (-views.get(p["id"], 0), not (p.get("media") or {}).get("image"), p.get("collected_at") or ""))
            if dps:
                sections.append(f'<h2 class="sec">{e(DOMAIN_ICON[d])} {e(d)} <a href="../../{cat_url(d)}">{len(dps)}개 →</a></h2>'
                                f'<div class="cards">{"".join(card(p, "../../") for p in dps[:6])}</div>')
        nav = (f'<p class="crumb">' + (f'<a href="../{order[i + 1]}/">← 지난주</a>' if i + 1 < len(order) else "")
               + (" · " if i + 1 < len(order) and i > 0 else "") + (f'<a href="../{order[i - 1]}/">다음 주 →</a>' if i > 0 else "")
               + '</p>')
        body = (f'<div class="doc"><span class="pill">{w}</span><h1>{start:%m월 %d일} – {end:%m월 %d일} 주간 요약</h1>'
                f'<p class="desc">이번 주 정리된 글 {len(ps)}개 · 가장 활발했던 도구: {e(top_tools)}</p>{nav}</div>'
                + "".join(sections))
        (root_dir / w).mkdir(exist_ok=True)
        (root_dir / w / "index.html").write_text(
            page(f"{start:%Y년 %m월 %d일} 주간 3D 소식 요약 - {SITE_TITLE}", body, "../../",
                 desc=f"{start:%m월 %d일} 주간 3D·게임엔진·VFX·AI 3D 소식 {len(ps)}개 요약"), encoding="utf-8")
    items = "".join(
        f'<a href="{w}/"><span><span class="t">{datetime.fromisocalendar(int(w[:4]), int(w[6:]), 1):%Y년 %m월 %d일} 주간</span>'
        f'<br><span class="k">글 {len(weeks[w])}개</span></span></a>' for w in order)
    body = ('<div class="doc"><h1>주간 요약</h1><p class="desc">매주 정리된 3D 소식을 분야별로 묶어 한눈에 봅니다. '
            '바쁜 한 주, 이것만 보면 흐름을 따라갈 수 있어요.</p></div>' + f'<div class="rank">{items or "<p>준비 중</p>"}</div>')
    (root_dir / "index.html").write_text(page(f"주간 요약 - {SITE_TITLE}", body, "../"), encoding="utf-8")


def indexnow_submit(hours: int = 3) -> str:
    """IndexNow: 최근 N시간 내 새 글 URL 을 검색엔진(네이버·Bing·Yandex·Seznam·Yep 공유)에 즉시 알림.
    키 파일은 static/<32자리hex>.txt 로 사이트 루트(/3dflowhub/)에 배포되어 있어야 한다."""
    import requests
    keys = [f.stem for f in (ROOT / "static").glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}", f.stem)]
    if not keys:
        return "키 파일 없음"
    cutoff = (datetime.utcnow().timestamp() - hours * 3600)
    urls = []
    for p in load_posts():
        try:
            ts = datetime.fromisoformat((p.get("collected_at") or "").replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            urls.append(f"{BASE_URL}/p/{p['id']}.html")
    if not urls:
        return "새 글 없음"
    urls += [f"{BASE_URL}/", f"{BASE_URL}/sitemap.xml"]
    body = {"host": BASE_URL.split("/")[2], "key": keys[0], "keyLocation": f"{BASE_URL}/{keys[0]}.txt",
            "urlList": urls[:10000]}
    r = requests.post("https://api.indexnow.org/indexnow", json=body, timeout=20,
                      headers={"Content-Type": "application/json; charset=utf-8"})
    return f"{len(urls)}개 URL → HTTP {r.status_code}"


def post_head(p: dict) -> str:
    """글 페이지 SEO: og:image·article 메타 + JSON-LD (BlogPosting, BreadcrumbList)."""
    url = f"{BASE_URL}/p/{p['id']}.html"
    img = (p.get("media") or {}).get("image") or ""
    date = (p.get("collected_at") or "")[:19]
    ld = [{
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": p["title_ko"][:110], "description": (p.get("summary") or "")[:300],
        "datePublished": date, "dateModified": date, "inLanguage": "ko-KR",
        "mainEntityOfPage": url, "url": url, **({"image": [img]} if img else {}),
        "author": {"@type": "Organization", "name": SITE_TITLE, "url": BASE_URL + "/"},
        "publisher": {"@type": "Organization", "name": SITE_TITLE, "url": BASE_URL + "/"},
        "articleSection": f"{p['domain']} › {p.get('category') or '기타'}",
        "keywords": ", ".join(p.get("tags") or []), "isBasedOn": p.get("url", ""),
    }, {
        "@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_TITLE, "item": BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": p["domain"], "item": f"{BASE_URL}/{cat_url(p['domain'])}"},
            {"@type": "ListItem", "position": 3, "name": p.get("category") or "기타",
             "item": f"{BASE_URL}/{cat_url(p['domain'], p.get('category') or '기타')}"},
            {"@type": "ListItem", "position": 4, "name": p["title_ko"][:110], "item": url}]}]
    # </script> 탈출 방지: '<' 를 유니코드 이스케이프
    js = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")
    return ((f'<meta property="og:image" content="{e(img)}">' if img else "") +
            f'<meta property="og:type" content="article"><meta property="og:url" content="{e(url)}">'
            f'<meta property="article:published_time" content="{e(date)}">'
            f'<script type="application/ld+json">{js}</script>')


def post_html(p: dict, root: str, related: list[dict]) -> str:
    m = p.get("media") or {}
    parts = [f'<div class="crumb"><a href="{root}{cat_url(p["domain"])}">{e(p["domain"])}</a> › '
             f'<a href="{root}{cat_url(p["domain"], p.get("category") or "기타")}">{e(p.get("category") or "기타")}</a>'
             + (f' › <a href="{root}{cat_url(p["domain"], p.get("category") or "기타")}{TOPIC_SLUG[p["topic"]]}/">'
                f'{e(p["topic"])}</a>' if p.get("topic") in TOPIC_SLUG else "") + ' · '
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
    assign_slugs(by_cat.keys())

    # 홈: 히어로 → 많이 본 글 → 이번 주 요약 → 분야 → 최신 글 카드 → 전체 목록
    weeks = sorted({w for w in (iso_week(p) for p in posts) if w}, reverse=True)
    tools_n = len({(d, c) for (d, c) in by_cat})
    tiles = []
    for d in board_domains():
        cats = sorted({c for (dd, c) in by_cat if dd == d}, key=lambda c: -len(by_cat[(d, c)]))
        lis = "".join(f'<li><a href="{{ROOT}}{cat_url(d, c)}">{e(c)}</a><span class="n">{len(by_cat[(d, c)])}</span></li>'
                      for c in cats[:8])
        tiles.append(f'<div class="box"><h3><span aria-hidden="true">{e(DOMAIN_ICON[d])}</span> '
                     f'<a href="{{ROOT}}{cat_url(d)}">{e(d)}</a><small class="n">{len(by_dom[d])}</small></h3>'
                     f'<ul>{lis or "<li>준비 중</li>"}</ul>'
                     f'<a class="more" href="{{ROOT}}{cat_url(d)}">게시판 전체 →</a></div>')
    picks = [p for p in posts if p.get("pick")]
    import guides as _guides
    learn_guides = _guides.load_all()
    learn_sec = (f'<h2 class="sec">기초 가이드 <a href="{{ROOT}}learn/">전체 보기 →</a></h2><div class="gcards">'
                 + "".join(guide_card(g, "{ROOT}") for g in learn_guides[:8]) + "</div>") if learn_guides else ""
    roundups = load_roundups(posts)
    guide_sec = (f'<h2 class="sec">도구별 정리 <a href="{{ROOT}}guide/">전체 보기 →</a></h2><div class="rank">'
                 + "".join(f'<a href="{{ROOT}}{guide_url(r["domain"], r["tool"])}"><span><span class="t">{e(r["title"])}</span>'
                           f'<br><span class="k">{e(r["domain"])} › {e(r["tool"])}</span></span></a>' for r in roundups[:6])
                 + "</div>") if roundups else ""
    pop = popular(posts, 8)
    rank = "".join(f'<a href="{{ROOT}}p/{p["id"]}.html"><span><span class="t">{e(p["title_ko"])}</span><br>'
                   f'<span class="k">{e(p["domain"])} › {e(p.get("category") or "")}</span></span></a>' for p in pop)
    latest = "".join(card(p, "{ROOT}") for p in posts[:7])
    week_card = ""
    if weeks:
        wk = [p for p in posts if iso_week(p) == weeks[0]]
        week_card = (f'<h2 class="sec">이번 주 요약 <a href="{{ROOT}}weekly/{weeks[0]}/">전체 보기 →</a></h2>'
                     f'<div class="cards">{"".join(card(p, "{ROOT}") for p in popular(wk, 3, days=10))}</div>')
    home_head = (
        f'<section class="hero"><h1>3D를 배우는 가장 빠른 길, <br>매일 정리되는 업계 소식</h1>'
        f'<p>Blender·3ds Max·언리얼·유니티·VFX·AI 3D까지 — 전 세계 소식과 튜토리얼을 한국어로 요약해 '
        f'도구별·주제별로 차곡차곡 쌓아 둡니다. 공부하고, 비교하고, 시야를 넓히세요.</p>'
        f'<div class="actions"><a class="btn primary" href="{{ROOT}}weekly/">이번 주 요약 보기</a>'
        f'<a class="btn ghost" href="{{ROOT}}about/">3dflowhub 소개 →</a></div>'
        f'<div class="stats"><span><b>{len(posts)}</b>정리된 글</span><span><b>{len(board_domains())}</b>분야</span>'
        f'<span><b>{tools_n}</b>도구·주제 게시판</span><span><b>{len(weeks)}</b>주간 요약</span></div></section>'
        f'<h2 class="sec">분야별 게시판</h2><div class="grid">{"".join(tiles)}</div>'
        + (f'<h2 class="sec">에디터 추천</h2><div class="cards">{"".join(card(p, "{ROOT}") for p in picks[:6])}</div>'
           if picks else "") +
        learn_sec + guide_sec +
        f'<h2 class="sec">많이 본 글</h2><div class="rank">{rank}</div>'
        f'{week_card}'
        f'<h2 class="sec">최신 글</h2><div class="cards lead-grid">{latest}</div>'
        f'<h2 class="sec">사이트 안내</h2><div class="links">'
        f'<a href="{{ROOT}}about/"><b>📘 소개</b><span>3dflowhub는 어떤 곳인가요</span></a>'
        f'<a href="{{ROOT}}weekly/"><b>🗓️ 주간 요약</b><span>한 주의 흐름을 한눈에</span></a>'
        f'<a href="{{ROOT}}guide/"><b>🧭 도구별 정리</b><span>도구마다 한 달 흐름과 핵심</span></a>'
        f'<a href="{{ROOT}}feed.xml"><b>📡 RSS 구독</b><span>새 글을 바로 받아보기</span></a>'
        f'<a href="{{ROOT}}contact/"><b>✉️ 문의·제보</b><span>자료 제보·의견·저작권 요청</span></a></div>'
        f'<h2 class="sec">전체 글</h2>')
    board_pages(posts, OUT, "", "전체 글", home_head, "", header_more='<h1>전체 글</h1>')

    # 도메인 게시판 + 세부 카테고리 게시판
    for d in board_domains():
        cats = sorted({c for (dd, c) in by_cat if dd == d}, key=lambda c: -len(by_cat[(d, c)]))

        def tabs(active: str | None, root: str) -> str:
            t = f'<a class="{"on" if active is None else ""}" href="{root}{cat_url(d)}">전체<span class="n">{len(by_dom[d])}</span></a>'
            return '<div class="tabs">' + t + "".join(
                f'<a class="{"on" if c == active else ""}" href="{root}{cat_url(d, c)}">{e(c)}<span class="n">{len(by_cat[(d, c)])}</span></a>'
                for c in cats) + "</div>"

        board_pages(by_dom[d], OUT / cat_url(d).rstrip("/"), "../../", d,
                    f"<h1>{e(DOMAIN_ICON[d])} {e(d)}</h1>" + tabs(None, "{ROOT}"), d)
        for c in cats:
            folder = OUT / "c" / DOMAIN_SLUG[d] / SLUG_MAP[(d, c)]
            items = by_cat[(d, c)]
            by_topic = {t: [p for p in items if p.get("topic") == t] for t in TOPIC_SLUG}

            def chips(active: str | None) -> str:
                up = "{ROOT}" + cat_url(d, c)  # 루트 기준 → page/2/ 같은 하위 페이지에서도 링크 유지
                base = f'<a class="{"on" if active is None else ""}" href="{up}">전체<span class="n">{len(items)}</span></a>'
                return '<div class="tabs chips">' + base + "".join(
                    f'<a class="{"on" if t == active else ""}" href="{up}{TOPIC_SLUG[t]}/">{e(t)}'
                    f'<span class="n">{len(ps)}</span></a>' for t, ps in by_topic.items() if ps) + "</div>"

            gd = next((r for r in roundups if (r["domain"], r["tool"]) == (d, c)), None)
            gd_link = (f'<p class="crumb"><a href="{{ROOT}}{guide_url(d, c)}">🧭 {e(gd["title"])} →</a></p>' if gd else "")
            board_pages(items, folder, "../../../", f"{d} › {c}",
                        f"<h1>{e(DOMAIN_ICON[d])} {e(d)} › {e(c)}</h1>" + gd_link + tabs(c, "{ROOT}") + chips(None), d)
            for t, ps in by_topic.items():
                if ps:
                    board_pages(ps, folder / TOPIC_SLUG[t], "../../../../", f"{d} › {c} › {t}",
                                f"<h1>{e(DOMAIN_ICON[d])} {e(d)} › {e(c)} › {e(t)}</h1>" + tabs(c, "{ROOT}")
                                + chips(t), d, indexable=len(ps) >= MIN_INDEXABLE)

    # 소개 페이지
    build_about(posts, by_dom, by_cat)
    # 주간 요약 (매주 자동 생성)
    build_weekly(posts)
    # 도구별 정리 (evolve 가 주 1회 생성한 roundup)
    build_guides(posts, roundups)
    # 기초 가이드 (영상 + 단계별 사용법)
    build_learn(learn_guides)

    # 문의 안내 페이지
    (OUT / "contact").mkdir(exist_ok=True)
    contact = (f"<article><h1>📮 광고·제휴 문의</h1>"
               f"<p>{SITE_TITLE}는 3D DCC · 게임 엔진 · VFX · AI 3D 소식을 한국어로 정리하는 큐레이션 사이트입니다.</p>"
               f"<h2>이런 문의를 환영합니다</h2><ul><li>광고 · 스폰서 콘텐츠</li><li>제품·서비스 소개 및 리뷰 협업</li>"
               f"<li>콘텐츠 제휴 · 교육/강의 협업</li><li>저작권 관련 요청 (게시 중단·출처 수정)</li></ul>"
               f"<h2>연락처</h2><p class=\"lead\">✉️ 이메일: {mail_link()}</p>"
               f"<p class=\"crumb\">회사/브랜드명, 문의 내용, 회신받을 연락처를 함께 보내주시면 빠르게 답변드리겠습니다.</p></article>")
    (OUT / "contact" / "index.html").write_text(page(f"광고·제휴 문의 - {SITE_TITLE}", contact, "../"), encoding="utf-8")

    # 개인정보처리방침 (애드센스 승인 필수 페이지)
    (OUT / "privacy").mkdir(exist_ok=True)
    cfg = site_cfg()
    privacy = (f"<article><h1>개인정보처리방침</h1><p>{SITE_TITLE}(이하 '사이트')는 회원가입·로그인이 없으며 "
               f"이름·연락처 등 개인정보를 직접 수집하지 않습니다.</p>"
               f"<h2>방문 통계</h2><p>{'방문 통계를 위해 GoatCounter 를 사용합니다. 쿠키를 사용하지 않으며 개인을 식별하지 않는 '
                                   '집계(페이지 조회수, 유입 경로, 브라우저 종류 등)만 수집합니다.' if cfg['goatcounter'] else '현재 별도의 방문 통계 도구를 사용하지 않습니다.'}</p>"
               f"<h2>광고</h2><p>사이트는 Google AdSense 등 제3자 광고를 게재할 수 있습니다. Google 을 비롯한 제3자 공급업체는 "
               f"쿠키를 사용해 사용자의 이전 방문 기록을 바탕으로 광고를 게재할 수 있으며, 사용자는 "
               f'<a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 '
               f"맞춤 광고를 해제할 수 있습니다. 자세한 내용은 "
               f'<a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener">Google 광고 정책</a>을 참고하세요.</p>'
               f"<h2>문의</h2><p>개인정보·저작권 관련 문의: {mail_link('[3dflowhub] 개인정보·저작권 문의')}</p>"
               f"<p class=\"crumb\">시행일: 2026-10-16</p></article>")
    (OUT / "privacy" / "index.html").write_text(page(f"개인정보처리방침 - {SITE_TITLE}", privacy, "../"), encoding="utf-8")
    if re.fullmatch(r"ca-pub-\d{10,20}", cfg["adsense"]):  # 애드센스 판매자 인증 파일
        (OUT / "ads.txt").write_text(f"google.com, {cfg['adsense'].replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n",
                                     encoding="utf-8")

    # 글 페이지
    aside_html = ('<section class="aside"><h2 class="sec">많이 본 글</h2><div class="cards">'
                  + "".join(card(q, "../") for q in popular(posts, 3)) + "</div></section>")
    (OUT / "p").mkdir(exist_ok=True)
    for p in posts:
        related = [r for r in by_cat[(p["domain"], p.get("category") or "기타")] if r["id"] != p["id"]][:3] or \
                  [r for r in by_dom[p["domain"]] if r["id"] != p["id"]][:3]
        (OUT / "p" / f"{p['id']}.html").write_text(
            page(f"{p['title_ko']} - {SITE_TITLE}", post_html(p, "../", related) + aside_html, "../", p["domain"],
                 p.get("summary") or SITE_DESC, f"{BASE_URL}/p/{p['id']}.html", post_head(p)), encoding="utf-8")

    # 검색 인덱스·RSS·사이트맵
    (OUT / "search.json").write_text(json.dumps(
        [{"i": p["id"], "t": p["title_ko"], "c": f'{p["domain"]} › {p.get("category") or ""}',
          "g": " ".join(p.get("tags") or [])} for p in posts], ensure_ascii=False), encoding="utf-8")
    items = "".join(f"<item><title>{e(p['title_ko'])}</title><link>{BASE_URL}/p/{p['id']}.html</link>"
                    f"<guid>{BASE_URL}/p/{p['id']}.html</guid><category>{e(p['domain'])}</category>"
                    f"<pubDate>{rfc822(p.get('collected_at'))}</pubDate>"
                    f"<description>{e(p.get('summary') or '')}</description></item>" for p in posts[:50])
    (OUT / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><?xml-stylesheet href="feed.xsl" type="text/xsl"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
                                  f'<atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>'
                                  f"<title>{SITE_TITLE}</title><link>{BASE_URL}/</link><description>{e(SITE_DESC)}"
                                  f"</description>{items}</channel></rss>", encoding="utf-8")
    urls = [f"{BASE_URL}/", f"{BASE_URL}/about/", f"{BASE_URL}/weekly/", f"{BASE_URL}/contact/", f"{BASE_URL}/privacy/"] + \
           [f"{BASE_URL}/weekly/{w}/" for w in sorted({w for w in (iso_week(p) for p in posts) if w})] + [f"{BASE_URL}/{cat_url(d)}" for d in board_domains()] + \
           [f"{BASE_URL}/{cat_url(d, c)}" for (d, c) in sorted(by_cat)] + \
           [f"{BASE_URL}/{cat_url(d, c)}{TOPIC_SLUG[t]}/" for (d, c), ps in sorted(by_cat.items())
            for t in sorted({p.get("topic") for p in ps if p.get("topic") in TOPIC_SLUG})
            if sum(1 for p in ps if p.get("topic") == t) >= MIN_INDEXABLE] + \
           [f"{BASE_URL}/learn/"] + [f"{BASE_URL}/{learn_url(g)}" for g in learn_guides] + \
           [f"{BASE_URL}/guide/"] + [f"{BASE_URL}/{guide_url(r['domain'], r['tool'])}" for r in roundups] + \
           [f"{BASE_URL}/p/{p['id']}.html" for p in posts]
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/'
                                     'schemas/sitemap/0.9">' + "".join(f"<url><loc>{e(u)}</loc></url>" for u in urls)
                                     + "</urlset>", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    return {"posts": len(posts), "boards": len(by_cat) + len(core.DOMAINS)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="노션 글을 content/posts 로 복원")
    ap.add_argument("--indexnow", action="store_true", help="최근 새 글을 IndexNow(네이버·Bing 등)에 알림 (배포 후)")
    a = ap.parse_args()
    if a.indexnow:
        print("IndexNow:", indexnow_submit())
        raise SystemExit(0)
    if a.backfill:
        print("노션 복원:", backfill_from_notion(), "개")
    print("빌드:", build())
