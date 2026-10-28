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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from urllib.parse import urlparse

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


def norm_adsense(v: str) -> str:
    """'pub-123…' 처럼 앞의 ca- 를 빼고 넣어도 동작하게 (예전엔 광고 스크립트가 아예 안 들어갔음)."""
    v = (v or "").strip()
    return "ca-" + v if re.fullmatch(r"pub-\d{10,20}", v) else v


def verify_code(v: str) -> str:
    """서치콘솔·서치어드바이저가 주는 <meta …content="코드"> 를 통째로 붙여넣어도 코드만 꺼냄."""
    m = re.search(r"""content=["']([^"']+)""", v or "")
    return (m.group(1) if m else (v or "")).strip()


def site_cfg() -> dict:
    """config.json 의 사이트 수익화/분석 설정 (대시보드 💰 탭에서 입력 → GitHub 반영)."""
    c = core._load_json(core.CONFIG_PATH, {})
    return {"goatcounter": (c.get("goatcounter_code") or "").strip(),
            "adsense": norm_adsense(c.get("adsense_client") or os.getenv("ADSENSE_CLIENT", "")),
            "google_verify": (c.get("google_site_verification") or "").strip(),
            "naver_verify": (c.get("naver_site_verification") or "").strip(),
            "base_url": (c.get("site_base_url") or BASE_URL).rstrip("/"),
            "newsletter": (c.get("newsletter_buttondown") or "").strip()}


def newsletter_box(root: str = "") -> str:
    """동의 기반 뉴스레터 구독 칸 (Buttondown, 이중 동의). 설정이 없으면 표시하지 않음."""
    user = site_cfg()["newsletter"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,40}", user):
        return ""
    return (f'<form class="nl" action="https://buttondown.com/api/emails/embed-subscribe/{e(user)}" method="post" '
            f'target="_blank"><b>📬 주간 3D 소식·검증된 스크립트 받아보기</b>'
            f'<span>매주 한 번, 구독 확인한 분께만 보냅니다. 언제든 메일 하단에서 수신거부할 수 있어요.</span>'
            f'<div><input type="email" name="email" required placeholder="이메일 주소" aria-label="이메일 주소">'
            f'<button type="submit">구독</button></div>'
            f'<small>구독하면 <a href="{root}privacy/">개인정보처리방침</a>에 동의하는 것으로 봅니다 '
            f'(수집: 이메일 · 목적: 뉴스레터 발송 · 보관: 수신거부 시까지).</small></form>')


def head_scripts() -> str:
    cfg, out = site_cfg(), []
    for name, key in (("google-site-verification", "google_verify"), ("naver-site-verification", "naver_verify")):
        code = verify_code(cfg[key])
        if re.fullmatch(r"[A-Za-z0-9_\-]{10,100}", code):  # 검색엔진 소유 확인 (구글 서치콘솔·네이버 서치어드바이저)
            out.append(f'<meta name="{name}" content="{code}">')
    if re.fullmatch(r"[a-z0-9-]{2,50}", cfg["goatcounter"]):  # 방문 통계 (쿠키 없음)
        out.append(f'<script data-goatcounter="https://{cfg["goatcounter"]}.goatcounter.com/count" '
                   f'async src="//gc.zgo.at/count.js"></script>')
    if re.fullmatch(r"ca-pub-\d{10,20}", cfg["adsense"]):  # 애드센스 자동 광고 (승인 후)
        out.append(f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{cfg["adsense"]}" crossorigin="anonymous"></script>')
    return "\n".join(out)


def mail_link(subject: str = "[3dflowhub] 광고·제휴 문의", text: str | None = None) -> str:
    """스팸 수집기 대응: 주소를 HTML 엔티티로 인코딩한 mailto 링크 (브라우저에서는 정상 표시·클릭)."""
    enc = "".join(f"&#{ord(c)};" for c in CONTACT_EMAIL)
    return f'<a href="mailto:{enc}?subject={quote(subject)}">{e(text) if text else enc}</a>'
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
.logo{display:flex;align-items:center;gap:10px;min-height:44px;flex:none;white-space:nowrap}
.logo .mark{flex:none;border-radius:8px;box-shadow:0 2px 8px rgba(94,92,230,.35);transition:transform .35s ease}
.logo:hover .mark{transform:rotate(-8deg) scale(1.06)}
.logo .word{font:800 21px/1 -apple-system,BlinkMacSystemFont,"SF Pro Display","Pretendard",system-ui,sans-serif;letter-spacing:-.04em}
.logo .w3d{background:linear-gradient(135deg,#0a84ff,#5e5ce6 55%,#bf5af2);-webkit-background-clip:text;background-clip:text;color:transparent;margin-right:1px}
.logo .wflow{color:var(--text)}.logo .whub{color:var(--muted);font-weight:600}
.logo:hover .wflow{color:var(--text)}
.topnav{display:flex;gap:2px;min-width:0;overflow-x:auto;scrollbar-width:none}.topnav a{white-space:nowrap;flex:none;font-size:14px;color:var(--text-2);padding:10px 10px;border-radius:10px}
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
.pager{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:28px 0}
.pager a{min-width:40px;min-height:40px;display:inline-flex;align-items:center;justify-content:center;border-radius:10px;background:var(--surface);border:1px solid var(--line)}
.pager a.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.pager{align-items:center}.pager .pg-nav{padding:0 14px}
.pager .pg-nav.off{min-height:40px;display:inline-flex;align-items:center;padding:0 14px;opacity:.35}
.pager .pg-gap{min-width:24px;text-align:center;color:var(--muted)}.pager .pg-count{display:none;color:var(--muted);padding:0 8px}
.pager a:hover{border-color:var(--accent)}.pager a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
@media(max-width:560px){.pager .pg-num,.pager .pg-gap{display:none}.pager .pg-count{display:inline}.pager{flex-wrap:nowrap}}

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

@media (max-width:1100px){.topnav a{padding:10px 7px;font-size:13px}}
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
.menupath{margin:12px 0 16px;padding:12px 14px;background:var(--surface);border:1px solid var(--line);border-radius:12px}
.menupath figcaption{font-size:12px;opacity:.7;margin-bottom:8px}
.menupath div{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.mp-chip{padding:5px 10px;border-radius:6px;border:1px solid var(--line);background:var(--bg);font:600 13px/1.3 ui-monospace,Consolas,monospace}
.mp-chip.last{border-color:var(--accent,#4f8cff);color:var(--accent,#4f8cff)}
.mp-arr{opacity:.5;font-weight:700}
.toolcard{margin:12px 0 18px}.toolcard img{width:100%;height:auto;max-height:320px;object-fit:cover;border-radius:14px;display:block}
.refs{padding-left:20px}.refs li{margin:6px 0}.refs .k{font-size:12px;opacity:.7}
.sgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(240px,100%),1fr));gap:14px}
.scard{display:grid;gap:4px;padding:10px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--text);text-decoration:none}
.scard img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:8px;background:var(--surface-2)}
.scard .k{font-size:12px;opacity:.75}
.nl{display:grid;gap:6px;margin:28px 0;padding:16px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}
.nl span,.nl small{font-size:13px;opacity:.8}.nl div{display:flex;gap:8px;flex-wrap:wrap}
.nl input{flex:1;min-width:180px;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text)}
.nl button{padding:10px 16px;border-radius:10px;border:0;background:var(--accent);color:#fff;font-weight:700;cursor:pointer}
.codebar{display:flex;gap:10px;align-items:center;margin:8px 0}
.codebar button,.codebar a{font:600 13px/1 inherit;padding:8px 12px;border-radius:8px;border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer;text-decoration:none}
pre.code{max-height:520px;overflow:auto;padding:14px;border-radius:12px;background:#0d1117;color:#e6edf3;font:13px/1.55 ui-monospace,Consolas,monospace;white-space:pre}
.docfigs{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(260px,100%),1fr));gap:14px;margin:12px 0}
.docfig{margin:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface)}
.docfig img{display:block;width:100%;height:auto;background:#fff}
.docfig figcaption{padding:8px 10px;font-size:12px;line-height:1.5;opacity:.85}
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
#results .row{display:block}#results .row.on{background:var(--accent-soft)}#results .row.s{font-size:13px;color:var(--muted);padding:8px 14px}
.lpath{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0}.lpath .k{grid-column:1/-1;font-size:13px;color:var(--muted)}
.lpath a{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-weight:600}
.lpath .next{text-align:right}.lpath a:hover{border-color:var(--accent)}
.savebtn{border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:99px;padding:6px 14px;
  font:inherit;font-size:14px;cursor:pointer;margin:4px 0 10px}.savebtn[aria-pressed="true"]{color:var(--accent);border-color:var(--accent)}
a.read{opacity:.62}a.read .t::after,a.read .kicker::after{content:" · 읽음";font-weight:400;color:var(--muted);font-size:12px}
#saved-list .row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.aiby{font-size:13px;color:var(--muted);margin:2px 0 14px}.aiby a{text-decoration:underline}.aiby .ok{color:#248a3d}
.optip{border-left:4px solid var(--accent);background:var(--accent-soft);border-radius:12px;padding:12px 16px;margin:14px 0}
.optip b{display:block;margin-bottom:4px}.optip p{margin:0;white-space:pre-line}
/* 홈 '도구별 기초 배우기' — 영상 썸네일 강조 */
.lt-hero{position:relative;display:block;aspect-ratio:16/9;border-radius:12px;overflow:hidden;margin:4px 0 10px;background:#000}
.lt-hero img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .25s}.lt-hero:hover img{transform:scale(1.03)}
.lt-hero::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 45%,rgba(0,0,0,.65))}
.lt-play{position:absolute;left:50%;top:45%;transform:translate(-50%,-50%);width:52px;height:52px;border-radius:50%;
  background:rgba(255,255,255,.92);color:#111;display:grid;place-items:center;font-size:20px;z-index:1;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.lt-cap{position:absolute;left:12px;right:12px;bottom:10px;color:#fff;font-weight:700;font-size:15px;z-index:1}
.lt-list{list-style:none;padding:0;margin:0}.lt-list li{border-top:1px solid var(--line)}.lt-list li:first-child{border-top:0}
.lt-list a{display:flex;align-items:center;gap:10px;padding:7px 0;min-height:44px}
.lt-th{width:64px;height:36px;border-radius:6px;object-fit:cover;flex:none;background:var(--accent-soft)}
.lt-ph{display:grid;place-items:center;font-size:16px}.lt-t{flex:1;min-width:0;line-height:1.35}
.lt-v{flex:none;font-size:12px;font-weight:600;color:var(--accent);background:var(--accent-soft);border-radius:99px;padding:2px 8px}
"""

LOGO_SVG = """<svg class="mark" viewBox="0 0 64 64" width="30" height="30" aria-hidden="true">
<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a84ff"/>
<stop offset=".55" stop-color="#5e5ce6"/><stop offset="1" stop-color="#bf5af2"/></linearGradient></defs>
<rect width="64" height="64" rx="15" fill="url(#lg)"/>
<ellipse class="orbit" cx="32" cy="33" rx="25" ry="10" fill="none" stroke="#fff" stroke-opacity=".45" stroke-width="2.2" transform="rotate(-22 32 33)"/>
<path d="M32 13 L48 22 L32 31 L16 22 Z" fill="#fff"/><path d="M16 22 L32 31 L32 50 L16 41 Z" fill="#fff" fill-opacity=".72"/>
<path d="M48 22 L32 31 L32 50 L48 41 Z" fill="#fff" fill-opacity=".45"/><circle cx="54.5" cy="22.5" r="3" fill="#fff"/></svg>"""

SEARCH_JS = ""  # 검색은 static/search.js (한/영 자판 변환·여러 단어·키보드 이동)


def og_default(domain: str = "") -> str:
    """대표 이미지가 없을 때 공유 미리보기 카드 (static/og/, make_og.py 로 생성)."""
    return f'<meta property="og:image" content="{BASE_URL}/og/{DOMAIN_SLUG.get(domain, "default")}.png">'            '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'


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
{og_default(domain_on) if 'og:image' not in extra_head else ''}
{head_scripts()}
<link rel="alternate" type="application/rss+xml" title="{SITE_TITLE}" href="{root}feed.xml">
<meta name="theme-color" content="#f5f5f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}assets/style.css"></head><body>
<a class="skip" href="#main">본문으로 건너뛰기</a>
<header><div class="wrap"><div class="top"><a class="logo" href="{root}" aria-label="{SITE_TITLE} 홈">{LOGO_SVG}<span class="word" aria-hidden="true"><span class="w3d">3d</span><span class="wflow">flow</span><span class="whub">hub</span></span></a>
<nav class="topnav" aria-label="사이트"><a href="{root}learn/">기초 가이드</a><a href="{root}saved/">☆ 저장</a><a href="{root}guide/">도구별 정리</a><a href="{root}recipes/">실무 파이프라인</a><a href="{root}weekly/">주간 요약</a><a href="{root}about/">소개</a><a href="{root}contact/">문의</a></nav>
<div class="search" role="search"><input id="q" type="search" placeholder="Blender, 언리얼, 가우시안…" aria-label="사이트 검색"></div></div>
<nav class="domains" aria-label="분야"><a href="{root}" class="{"on" if not domain_on else ""}">전체</a>{nav}<span class="sep mob" aria-hidden="true"></span><a class="mob" href="{root}learn/">📚 기초 가이드</a><a class="mob" href="{root}saved/">☆ 저장</a><a class="mob" href="{root}guide/">🧭 도구별 정리</a><a class="mob" href="{root}recipes/">🔧 실무 파이프라인</a><a class="mob" href="{root}weekly/">🗓️ 주간 요약</a><a class="mob" href="{root}about/">📘 소개</a><a class="mob" href="{root}contact/">✉️ 문의</a></nav></div></header>
<main class="wrap" id="main"><div id="results" class="board" hidden style="margin-top:20px" aria-live="polite"></div>{body}</main>
<footer><div class="wrap"><div class="cols"><a href="{root}about/">소개</a><a href="{root}showcase/">이번 주 작품</a><a href="{root}resources/">추천 자료</a><a href="{root}weekly/">주간 요약</a>
<a href="{root}feed.xml">RSS 구독</a><a href="{root}contact/">문의</a><a href="{root}privacy/">개인정보처리방침</a></div>
© {datetime.now():%Y} {SITE_TITLE} · 3D를 배우고 나누는 사람들을 위한 큐레이션 · 원문 저작권은 각 출처에 있습니다 · {mail_link()}</div></footer>
<script>const ROOT="{root}";</script><script src="{root}search.js" defer></script><script src="{root}user.js" defer></script></body></html>"""


def kst_date(ts: str) -> str:
    """수집 시각(UTC) → 한국 날짜 'YYYY-MM-DD'. 한국 0~9시에 모은 글이 전날로 보이던 문제."""
    if not ts:
        return ""
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromisoformat(ts)
        if d.tzinfo is None:
            return ts[:10]
        return d.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    except ValueError:
        return ts[:10]


def fallback_thumb(p: dict) -> str:
    """대표 이미지가 없는 글: 도구 이름 카드(static/og/tool-*.png, make_og.py) → 없으면 분야 카드. 사이트 루트 기준 경로."""
    from make_og import tool_slug
    tool = p.get("category") or ""
    if tool and (ROOT / "static" / "og" / f"tool-{tool_slug(tool)}.png").exists():
        return f"og/tool-{tool_slug(tool)}.png"
    return f"og/{DOMAIN_SLUG.get(p.get('domain'), 'default')}.png"


def row(p: dict, root: str) -> str:
    img = (p.get("media") or {}).get("image")
    thumb = (f'<img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if img
             else f'<img src="{root}{fallback_thumb(p)}" alt="" loading="lazy">')
    return (f'<a class="row" href="{root}p/{p["id"]}.html">{thumb}<span><span class="t">{e(p["title_ko"])}</span><br>'
            f'<span class="s">{e(p.get("summary") or "")}</span></span>'
            f'<span class="side"><span class="badge">{e(p.get("category") or "기타")}'
            f'{" · " + e(p["topic"]) if p.get("topic") else ""}</span>'
            f'<span class="date">{kst_date(p.get("collected_at") or "")}</span></span></a>')


MIN_INDEXABLE = 3  # 글이 이보다 적은 하위 게시판은 noindex (얇은 페이지가 사이트 품질 평가를 떨어뜨리지 않도록)


def card(p: dict, root: str) -> str:
    img = (p.get("media") or {}).get("image")
    pic = (f'<div class="img"><img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer"></div>' if img
           else f'<div class="img"><img src="{root}{fallback_thumb(p)}" alt="" loading="lazy"></div>')
    return (f'<a class="card" href="{root}p/{p["id"]}.html">{pic}<div class="body">'
            f'<span class="kicker">{e(p.get("category") or p["domain"])}{" · " + e(p["topic"]) if p.get("topic") else ""}</span>'
            f'<span class="t">{e(p["title_ko"])}</span><span class="s">{e(p.get("summary") or "")}</span>'
            f'<span class="meta">{kst_date(p.get("collected_at") or "")}</span></div></a>')


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


def iso_tz(s: str) -> str:
    """구조화 데이터용 날짜 — 시간대가 빠지면 Google 이 다르게 해석하므로 오프셋을 꼭 붙임 (없으면 UTC)."""
    s = (s or "").strip().replace("Z", "+00:00")
    if not s:
        return ""
    if len(s) == 10:
        return s
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return s[:19]
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")


def iso_week(p: dict) -> str:
    try:
        y, w, _ = datetime.fromisoformat(kst_date(p.get("collected_at") or "")).isocalendar()
        return f"{y}-W{w:02d}"
    except ValueError:
        return ""


def page_window(n: int, total: int, span: int = 2) -> list:
    """보여 줄 페이지 번호 — 처음·끝 + 현재 앞뒤 span 개, 건너뛴 곳은 None(…)."""
    keep = sorted({1, total, *range(max(1, n - span), min(total, n + span) + 1)})
    out: list = []
    for k in keep:
        if out and k - out[-1] > 1:
            out.append(None if k - out[-1] > 2 else k - 1)  # 한 칸만 비면 … 대신 그 번호
        out.append(k)
    return out


def pager_html(n: int, total: int, href) -> str:
    """페이지 이동: ‹ 이전 · 1 … 5 6 [7] 8 9 … 24 · 다음 › (번호를 다 늘어놓지 않음, 휴대폰에선 '7 / 24')."""
    if total <= 1:
        return ""
    items = [f'<a class="pg-nav" href="{href(n - 1)}" rel="prev" aria-label="이전 페이지">‹ 이전</a>' if n > 1
             else '<span class="pg-nav off" aria-hidden="true">‹ 이전</span>']
    for k in page_window(n, total):
        if k is None:
            items.append('<span class="pg-gap" aria-hidden="true">…</span>')
        elif k == n:
            items.append(f'<a class="pg-num on" href="{href(k)}" aria-current="page">{k}</a>')
        else:
            items.append(f'<a class="pg-num" href="{href(k)}" aria-label="{k}페이지">{k}</a>')
    items.append(f'<span class="pg-count">{n} / {total}</span>')
    items.append(f'<a class="pg-nav" href="{href(n + 1)}" rel="next" aria-label="다음 페이지">다음 ›</a>' if n < total
                 else '<span class="pg-nav off" aria-hidden="true">다음 ›</span>')
    return f'<nav class="pager" aria-label="페이지 이동">{"".join(items)}</nav>'


def board_pages(posts: list[dict], out_dir: Path, root: str, title: str, header: str, domain_on: str,
                indexable: bool = True, header_more: str | None = None) -> None:
    """게시판 목록 (페이지네이션: index.html, page/2/ ...)."""
    pages = [posts[i:i + PAGE_SIZE] for i in range(0, max(len(posts), 1), PAGE_SIZE)] or [[]]
    for n, chunk in enumerate(pages, 1):
        r = root + ("../../" if n > 1 else "")
        base = f"{r}{out_dir.relative_to(OUT).as_posix()}/"
        pager = pager_html(n, len(pages), lambda k: base + ("" if k == 1 else f"page/{k}/"))
        head = header if n == 1 or header_more is None else header_more
        body = head.replace("{ROOT}", r) + '<div class="board">' + ("".join(row(p, r) for p in chunk)
                                                                       or '<div class="row">아직 글이 없습니다.</div>') \
            + f'</div>{pager}'
        d = out_dir if n == 1 else out_dir / "page" / str(n)
        d.mkdir(parents=True, exist_ok=True)
        robots = "" if indexable else '<meta name="robots" content="noindex,follow">'
        rel = d.relative_to(OUT).as_posix()
        if rel == "." and n == 1:  # 홈: 브랜드 + 무엇을 하는 사이트인지 (검색 결과 제목)
            full = f"{SITE_TITLE} — 3D·게임 엔진·VFX·AI 3D 소식과 기초 가이드"
        else:  # 2쪽 이후 제목 중복 방지
            full = f"{title}{f' {n}페이지' if n > 1 else ''} - {SITE_TITLE}"
        canonical = f"{BASE_URL}/" + ("" if rel == "." else quote(rel) + "/")
        (d / "index.html").write_text(page(full, body, r, domain_on, extra_head=robots, canonical=canonical),
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
<h2 class="sec">어떻게 만들어지나요 (AI 와 사람의 역할)</h2>
<p>공식 블로그·전문 매체·커뮤니티·논문(arXiv)에서 새 소식을 수집하고, <b>AI 가 핵심을 한국어로 요약·해설</b>해
<b>분야 › 도구 › 콘텐츠 유형</b>으로 분류합니다. 기초 가이드는 공식 문서와 튜토리얼 영상을 바탕으로 AI 가 정리합니다.
<b>사람(운영자)</b>은 주제와 맞지 않거나 틀린 글을 숨기고, 기초 가이드를 검토해 <b>✔ 에디터 검토 완료</b>를 표시하며,
직접 해 본 경험은 <b>✍️ 운영자 실무 팁</b>으로 덧붙입니다. 모든 페이지 상단에 어떻게 만들어졌는지 표시합니다.</p>
<h2 class="sec">편집 원칙</h2>
<ul>
<li><b>사실과 출처</b> — 원문에 없는 내용을 지어내지 않고, 모든 글에 원문 링크를 답니다. 정확한 내용과 저작권은 원문이 기준입니다.</li>
<li><b>정식 표기</b> — 소프트웨어·메뉴·기능 이름은 공식 영문 표기를 씁니다 (MAXScript, Geometry Nodes 등).</li>
<li><b>오류 정정</b> — 틀린 내용은 각 페이지의 <b>오류 제보</b>로 알려 주시면 확인 후 고치거나 내립니다.</li>
<li><b>저작권</b> — 원문 전체를 옮기지 않고 요약·해설만 하며, 이미지·영상은 원본 링크·임베드로만 씁니다. 게시 중단 요청은 즉시 처리합니다.</li>
<li><b>광고·후원</b> — 현재 유료 게재·후원 콘텐츠는 없습니다. 생기면 해당 글에 분명히 표시합니다.</li>
</ul>
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
        folder = OUT / unquote(guide_url(d, t)).rstrip("/")  # 한글 도구명: 링크는 %인코딩, 폴더는 원래 글자
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


COPY_JS = """<script>document.querySelectorAll('.copy').forEach(b=>b.addEventListener('click',()=>{
navigator.clipboard.writeText(document.getElementById(b.dataset.for).textContent).then(()=>{b.textContent='복사됨 ✓';
setTimeout(()=>b.textContent='코드 복사',1500)})}))</script>"""
EXT = {"python": "py", "maxscript": "ms"}


def build_recipes(recipes_: list[dict], posts: list[dict]) -> None:
    """실무 파이프라인: AI 3D 소식을 작업 툴(Blender 애드온·MAXScript·Maya)에 붙여 쓰는 방법 + 스크립트."""
    root_dir = OUT / "recipes"
    root_dir.mkdir(exist_ok=True)
    by_id = {p["id"]: p for p in posts}
    for r in recipes_:
        folder = root_dir / r["id"]
        folder.mkdir(exist_ok=True)
        root = "../../"
        fname = f"3dflowhub_{r['id']}.{EXT.get(r['lang'], 'txt')}"
        (folder / fname).write_text(r["script"], encoding="utf-8")  # 바로 받을 수 있는 스크립트 파일
        flow = '<span class="mp-arr" aria-hidden="true">›</span>'.join(
            f'<span class="mp-chip{" last" if i == len(r["pipeline"]) - 1 else ""}">{e(s["tool"])}</span>'
            for i, s in enumerate(r["pipeline"]))
        stages = "".join(f'<li><b>{e(s["tool"])}</b> — {e(s["action"])}</li>' for s in r["pipeline"])
        srcs = [by_id[i] for i in r.get("sources", []) if i in by_id]
        lang = "Python" if r["lang"] == "python" else "MAXScript"
        body = (
            f'<article class="doc guide"><p class="crumb"><a href="{root}recipes/">실무 파이프라인</a> › '
            f'{e(r["category"])} › {e(r["host"])}</p><h1>{e(r["title"])}</h1>'
            f'<p class="aiby">🤖 AI 3D 게시판 소식을 바탕으로 AI 가 설계 · {e(r.get("checked", ""))} · '
            + mail_link("[3dflowhub] 파이프라인 오류 제보: " + r["title"][:40], "오류 제보") + '</p>'
            + f'<p class="lead">{e(r["problem"])}</p>'
            + f'<figure class="menupath" aria-label="파이프라인"><figcaption>파이프라인</figcaption><div>{flow}</div></figure>'
            + f'<ol class="steps">{stages}</ol>'
            + f'<h2>스크립트 ({e(r["host"])} · {lang})</h2>'
            + f'<div class="codebar"><button class="copy" type="button" data-for="code">코드 복사</button>'
              f'<a href="{e(fname)}" download>파일 받기</a></div>'
            + f'<pre class="code"><code id="code">{e(r["script"])}</code></pre>'
            + (f'<h2>설치</h2><ol>{"".join(f"<li>{e(x)}</li>" for x in r["install"])}</ol>' if r.get("install") else "")
            + (f'<h2>사용법</h2><ol>{"".join(f"<li>{e(x)}</li>" for x in r["usage"])}</ol>' if r.get("usage") else "")
            + (f'<h2>한계와 주의</h2><ul class="warn">{"".join(f"<li>{e(x)}</li>" for x in r["limits"])}</ul>'
               if r.get("limits") else "")
            + '<p class="crumb">⚠️ 반드시 장면 사본에서 먼저 실행해 보세요.</p></article>'
            + (f'<h2 class="sec">근거가 된 소식</h2><div class="cards">{"".join(card(q, root) for q in srcs)}</div>'
               if srcs else "")
            + COPY_JS)
        (folder / "index.html").write_text(
            page(f"{r['title']} - {SITE_TITLE}", body, root, domain_on=r.get("domain", ""), desc=r["problem"],
                 canonical=f"{BASE_URL}/recipes/{r['id']}/"), encoding="utf-8")
    items = "".join(f'<a href="{e(r["id"])}/"><span><span class="t">{e(r["title"])}</span><br>'
                    f'<span class="k">{e(r["category"])} → {e(r["host"])} · {e(r.get("at", "")[:10])}</span></span></a>'
                    for r in recipes_)
    body = ('<div class="doc"><h1>실무 파이프라인</h1><p class="desc">AI 3D 소식을 실제 작업에 붙여 쓰는 방법을 정리하고, '
            'Blender 애드온·MAXScript·Maya 스크립트로 바로 쓸 수 있게 제공합니다. 스크립트는 문법 검사만 거쳤으니 '
            '장면 사본에서 먼저 실행해 보세요.</p></div>'
            + f'<div class="rank">{items or "<p>준비 중입니다 — AI 3D 소식이 쌓인 분야부터 차례로 만들어집니다.</p>"}</div>')
    (root_dir / "index.html").write_text(page(f"실무 파이프라인 - {SITE_TITLE}", body, "../"), encoding="utf-8")


def build_showcase() -> None:
    """이번 주 작품: 작가 허락을 받은 커뮤니티 포트폴리오만 (showcase.published)."""
    import showcase
    items = showcase.published()
    folder = OUT / "showcase"
    folder.mkdir(exist_ok=True)
    cards = "".join(
        f'<a class="scard" href="{e(i["url"])}" target="_blank" rel="noopener">'
        + (f'<img src="{e(i["image"])}" alt="{e(i["title"])}" loading="lazy">' if i.get("image") else "")
        + f'<span class="t">{e(i["title"])}</span><span class="k">{e(i["artist"])}'
        + (f' · {e(i["note"])}' if i.get("note") else "") + "</span></a>" for i in items)
    body = ('<div class="doc"><h1>이번 주 작품</h1><p class="desc">커뮤니티에 올라온 멋진 3D 작업을 <b>작가님 허락을 받아</b> 소개합니다. '
            '작품을 누르면 원본 페이지로 이동합니다. 소개를 원하시거나 내리기를 원하시면 '
            + mail_link("[3dflowhub] 이번 주 작품 문의", "알려 주세요") + '.</p></div>'
            + (f'<div class="sgrid">{cards}</div>' if cards else '<p>첫 소개 작품을 준비하고 있습니다.</p>')
            + newsletter_box("../"))
    (folder / "index.html").write_text(page(f"이번 주 작품 - {SITE_TITLE}", body, "../", desc="허락을 받아 소개하는 3D 작가 작품",
                                            canonical=f"{BASE_URL}/showcase/"), encoding="utf-8")


def build_resources() -> None:
    """추천 자료: 운영자가 실무에서 참고해 온 외부 자료 링크 모음 (내용 복사 없이 제목·출처·링크만)."""
    d = core._load_json(core.ROOT / "content" / "resources.json", {})
    items = d.get("items") or []
    if not items:
        return
    folder = OUT / "resources"
    folder.mkdir(exist_ok=True)
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(it["category"], []).append(it)
    body = ('<div class="doc"><h1>추천 자료</h1><p class="desc">운영자가 실무에서 참고해 온 튜토리얼·도구·문서 모음입니다. '
            '각 자료의 저작권은 원작자에게 있으며, 여기서는 제목과 출처, 링크만 소개합니다.</p>'
            + "".join(f'<h2>{e(c)}</h2><ul class="refs">' + "".join(
                f'<li><a href="{e(i["url"])}" target="_blank" rel="noopener">{e(i["title"])}</a>'
                f' <span class="k">{e(i["source"])}</span></li>' for i in its) + "</ul>" for c, its in groups.items())
            + '<p class="crumb">링크가 끊겼거나 원작자가 삭제를 원하면 ' + mail_link("[3dflowhub] 추천 자료 문의", "알려 주세요") + '.</p></div>')
    (folder / "index.html").write_text(page(f"추천 자료 - {SITE_TITLE}", body, "../", desc="3D·게임 엔진 실무 추천 자료 모음",
                                            canonical=f"{BASE_URL}/resources/"), encoding="utf-8")


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


def related_posts_for_guide(g: dict, posts: list[dict], n: int = 3) -> list[dict]:
    """가이드와 같은 도구의 새 소식 — 기능 이름(예: Bend)이 제목에 있으면 먼저."""
    tool = g["tool"].lower()
    word = g["name"].split()[0].lower()
    same = [p for p in posts if tool in (p.get("category") or "").lower() or tool in p["title_ko"].lower()]
    same.sort(key=lambda p: p.get("collected_at") or "", reverse=True)  # 최신 순
    same.sort(key=lambda p: word not in (p["title_ko"] + " " + p.get("title", "")).lower())  # 기능 이름 일치 우선 (안정 정렬)
    return same[:n]


def guide_faq(g: dict) -> dict | None:
    """'자주 하는 실수 → 해결' 을 FAQPage 구조화 데이터로 (검색 결과에 질문·답 펼침)."""
    qa = []
    for m in g.get("mistakes") or []:
        if "→" in m:
            q, a = [x.strip() for x in m.split("→", 1)]
            qa.append({"@type": "Question", "name": f"{g['tool']} {g['name'].split(' modifier')[0]}: {q} 어떻게 하나요?",
                       "acceptedAnswer": {"@type": "Answer", "text": a}})
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": qa} if qa else None


def menu_diagram(path: list[str]) -> str:
    """메뉴 경로 도식: 클릭 순서대로 UI 이름을 버튼 모양으로 이어 보여줌 (이미지 파일 없이 HTML·CSS)."""
    if len(path) < 2:
        return ""
    chips = '<span class="mp-arr" aria-hidden="true">›</span>'.join(
        f'<span class="mp-chip{" last" if i == len(path) - 1 else ""}">{e(x)}</span>' for i, x in enumerate(path))
    return f'<figure class="menupath" aria-label="메뉴 경로: {e(" > ".join(path))}"><figcaption>메뉴 경로</figcaption><div>{chips}</div></figure>'


def doc_figures(images: list[dict]) -> str:
    """공식 문서 그림 (출처·라이선스 표기). 원본은 공식 문서 서버에서 불러옴."""
    if not images:
        return ""
    import guides
    figs = []
    for im in images:
        host = urlparse(im["source"]).netloc
        name, lic, lic_url = guides.DOC_IMAGE_LICENSE.get(host, (host, "", ""))
        cap = im.get("caption") or im.get("alt") or ""
        figs.append(f'<figure class="docfig"><img src="{e(im["src"])}" alt="{e(im.get("alt") or cap)}" loading="lazy">'
                    f'<figcaption>{e(cap)}{" · " if cap else ""}출처: <a href="{e(im["source"])}" target="_blank" rel="noopener">{e(name)}</a>'
                    + (f' (<a href="{e(lic_url)}" target="_blank" rel="noopener license">{e(lic)}</a>)' if lic else "")
                    + "</figcaption></figure>")
    return f'<h2>화면으로 보기</h2><div class="docfigs">{"".join(figs)}</div>'


def build_learn(guides_: list[dict], posts: list[dict] | None = None) -> None:
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
        path = [o for o in guides_ if o["tool"] == g["tool"]]  # 도구별 학습 순서 (목록 순)
        i = path.index(g)
        prv, nxt = (path[i - 1] if i > 0 else None), (path[i + 1] if i + 1 < len(path) else None)
        same = [o for o in path if o["id"] != g["id"]][:4]
        news = related_posts_for_guide(g, posts or [])
        nav_path = (f'<nav class="lpath" aria-label="학습 경로"><span class="k">{e(g["tool"])} 학습 경로 {i + 1} / {len(path)}</span>'
                    + (f'<a class="prev" href="{root}{learn_url(prv)}">← {e(prv["title"].split(" — ")[0])}</a>' if prv else "<span></span>")
                    + (f'<a class="next" href="{root}{learn_url(nxt)}">{e(nxt["title"].split(" — ")[0])} →</a>' if nxt else "<span></span>")
                    + "</nav>")
        how_to = {"@context": "https://schema.org", "@type": "HowTo", "name": g["title"], "description": g.get("summary", ""),
                  "inLanguage": "ko", "step": [{"@type": "HowToStep", "position": i + 1, "text": t} for i, t in enumerate(g["steps"])]}
        if vids:
            how_to["video"] = {"@type": "VideoObject", "name": vids[0]["title"], "embedUrl": f"https://www.youtube.com/embed/{vids[0]['id']}",
                               "thumbnailUrl": f"https://i.ytimg.com/vi/{vids[0]['id']}/hqdefault.jpg",
                               "uploadDate": g.get("at", "")[:10], "description": g.get("summary", "")}
        body = (
            f'<article class="doc guide"><p class="crumb"><a href="{root}learn/">기초 가이드</a> › {e(g["tool"])} › {e(g["group"])}</p>'
            f'<h1>{e(g["title"])}</h1>'
            + ('<p class="aiby">✍️ 운영자 실무 노트를 바탕으로 정리 · ' if g.get("by_operator")
               else '<p class="aiby">🤖 공식 문서·튜토리얼 영상을 바탕으로 AI 가 정리 · ')
            + ('<b class="ok">✔ 에디터 검토 완료</b>' if g.get("reviewed") else '에디터 검토 전')
            + ' · ' + mail_link("[3dflowhub] 가이드 오류 제보: " + g["title"][:40], "오류 제보") + '</p>'
            + f'<p class="lead">{e(g.get("summary", ""))}</p>'
            + (f'<div class="optip"><b>✍️ 운영자 실무 팁</b><p>{e(g["tip"])}</p></div>' if g.get("tip") else "")
            + (f'<div class="vids{" two" if len(vids) > 1 else ""}">{"".join(yt_facade(v) for v in vids)}</div>' if vids else "")
            + (f'<h2>이럴 때 씁니다</h2><ul>{"".join(f"<li>{e(x)}</li>" for x in g.get("when", []))}</ul>' if g.get("when") else "")
            + f'<h2>따라 하기</h2>' + menu_diagram(g.get("menu_path") or []) + f'<ol class="steps">{steps}</ol>'
            + doc_figures(g.get("images") or [])
            + (f'<h2>주요 옵션</h2><table class="params"><thead><tr><th>옵션</th><th>효과</th></tr></thead><tbody>{params}</tbody></table>'
               if params else "")
            + (f'<h2>활용 예시</h2><div class="ex">{exs}</div>' if exs else "")
            + (f'<h2>자주 하는 실수</h2><ul class="warn">{"".join(f"<li>{e(x)}</li>" for x in g.get("mistakes", []))}</ul>'
               if g.get("mistakes") else "")
            + (f'<p class="crumb">함께 알아두면 좋은 기능: {e(", ".join(g["related"]))}</p>' if g.get("related") else "")
            + f'<p class="crumb">📖 <a href="{e(g["doc"])}" target="_blank" rel="noopener">{e(g["tool"])} 공식 문서에서 자세히 보기</a>'
            + (" · 영상: " + ", ".join(f'<a href="https://www.youtube.com/watch?v={e(v["id"])}" target="_blank" rel="noopener">'
                                       f'{e(v["author"])}</a>' for v in vids) if vids else "")
            + "</p></article>" + nav_path
            + (f'<h2 class="sec">{e(g["tool"])} 관련 새 소식</h2><div class="cards">{"".join(card(q, root) for q in news)}</div>'
               if news else "")
            + (f'<h2 class="sec">{e(g["tool"])} 기초 더 보기</h2><div class="gcards">{"".join(guide_card(o, root) for o in same)}</div>'
               if same else "")
            + YT_JS)
        faq = guide_faq(g)
        # TechArticle(작성일·주제) + 경로(Breadcrumb) — HowTo/FAQ 리치결과는 줄었으니 기본 기사 정보를 확실히
        g_url = f"{BASE_URL}/{learn_url(g)}"
        article = [{"@context": "https://schema.org", "@type": "TechArticle", "headline": g["title"][:110],
                    "description": (g.get("summary") or "")[:300], "inLanguage": "ko-KR", "url": g_url,
                    "mainEntityOfPage": g_url, "datePublished": iso_tz(g.get("at") or ""),
                    "dateModified": iso_tz(g.get("at") or ""), "about": f'{g["tool"]} {g["name"]}',
                    "proficiencyLevel": "Beginner",
                    "author": {"@type": "Organization", "name": SITE_TITLE, "url": BASE_URL + "/"},
                    "publisher": {"@type": "Organization", "name": SITE_TITLE, "url": BASE_URL + "/"}},
                   {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                       {"@type": "ListItem", "position": 1, "name": SITE_TITLE, "item": BASE_URL + "/"},
                       {"@type": "ListItem", "position": 2, "name": "기초 가이드", "item": f"{BASE_URL}/learn/"},
                       {"@type": "ListItem", "position": 3, "name": g["title"][:80], "item": g_url}]}]
        head = f'<script type="application/ld+json">{json.dumps(article, ensure_ascii=False)}</script>' +             f'<script type="application/ld+json">{json.dumps(how_to, ensure_ascii=False)}</script>' + (
            f'<script type="application/ld+json">{json.dumps(faq, ensure_ascii=False)}</script>' if faq else "") + (
            f'<meta property="og:image" content="https://i.ytimg.com/vi/{e(vids[0]["id"])}/hqdefault.jpg">' if vids
            else f'<meta property="og:image" content="{BASE_URL}/og/learn.png">')
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
            '<b>영상</b>과 <b>따라 하기 단계</b>, <b>활용 예시</b>로 정리합니다. 새 소식과 달리 언제 봐도 유효한 레퍼런스예요. · <a href="../resources/">추천 자료 모음 →</a></p></div>'
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
                + "".join(sections) + newsletter_box("../../"))
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


THIN_CHARS = 600  # 본문이 이보다 짧고 3D 전문 용어도 적으면 '얇은 글'(현재 약 15%) — 검색 노출 제외(noindex), 사이트에는 유지


def is_thin(p: dict) -> bool:
    """짧고(600자 미만) 얕은(3D 용어 3개 미만) 요약 — 대량 생성 콘텐츠로 보일 위험이 큰 글."""
    text = " ".join(f"{s.get('heading', '')} {s.get('body', '')}" for s in (p.get("sections") or []) if isinstance(s, dict))
    if len(text) >= THIN_CHARS:
        return False
    low = (text + " " + (p.get("summary") or "") + " " + (p.get("insight") or "")).lower()
    terms = ("blender", "3ds max", "maya", "zbrush", "houdini", "substance", "unreal", "unity", "cinema 4d", "maxscript",
             "python", "usd", "gltf", "shader", "rigging", "mesh", "polygon", "uv", "pbr", "render", "gaussian",
             "블렌더", "맥스", "마야", "지브러시", "후디니", "언리얼", "유니티", "셰이더", "리깅", "폴리곤", "렌더")
    return sum(t in low for t in terms) < 3


def post_head(p: dict) -> str:
    """글 페이지 SEO: og:image·article 메타 + JSON-LD (BlogPosting, BreadcrumbList)."""
    url = f"{BASE_URL}/p/{p['id']}.html"
    thin = '<meta name="robots" content="noindex,follow">' if is_thin(p) else ""
    img = (p.get("media") or {}).get("image") or ""
    date = iso_tz(p.get("collected_at") or "")
    ld = [{
        "@context": "https://schema.org", "@type": "BlogPosting",
        "headline": p["title_ko"][:110], "description": (p.get("summary") or "")[:300],
        "datePublished": date, "dateModified": date, "inLanguage": "ko-KR",
        "mainEntityOfPage": url, "url": url, "image": [img or f"{BASE_URL}/{fallback_thumb(p)}"],
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
    return ((f'<meta property="og:image" content="{e(img)}">' if img else
             f'<meta property="og:image" content="{BASE_URL}/{fallback_thumb(p)}">') +
            f'<meta property="og:type" content="article"><meta property="og:url" content="{e(url)}">'
            f'<meta property="article:published_time" content="{e(date)}">'
            f'<script type="application/ld+json">{js}</script>' + thin)


def post_html(p: dict, root: str, related: list[dict]) -> str:
    m = p.get("media") or {}
    parts = [f'<div class="crumb"><a href="{root}{cat_url(p["domain"])}">{e(p["domain"])}</a> › '
             f'<a href="{root}{cat_url(p["domain"], p.get("category") or "기타")}">{e(p.get("category") or "기타")}</a>'
             + (f' › <a href="{root}{cat_url(p["domain"], p.get("category") or "기타")}{TOPIC_SLUG[p["topic"]]}/">'
                f'{e(p["topic"])}</a>' if p.get("topic") in TOPIC_SLUG else "") + ' · '
             f'{kst_date(p.get("collected_at") or "")}</div><h1>{e(p["title_ko"])}</h1>',
             f'<p class="aiby">🤖 원문을 AI 가 한국어로 요약·해설한 글입니다'
             + (' · 커뮤니티 토론·튜토리얼을 참고해 실무 내용을 보강했습니다' if p.get("refs") or p.get("videos") else "")
             + ' · 정확한 내용은 원문 기준 · '
             f'{mail_link("[3dflowhub] 오류 제보: " + p["title_ko"][:40], "오류 제보")}</p>']
    tip = core.tips().get("p:" + p["id"])
    if m.get("image"):
        parts.append(core.image_figure(m["image"], p["url"], p["title_ko"]))
    elif not core.VIDEO_RE.search(m.get("video") or ""):  # 원문 이미지·영상이 없으면 도구 카드로 첫 화면을 채움
        parts.append(f'<figure class="toolcard"><img src="{root}{fallback_thumb(p)}" '
                     f'alt="{e(p.get("category") or p["domain"])}" width="1200" height="630"></figure>')
    if (v := core.VIDEO_RE.search(m.get("video") or "")):
        src = f"https://www.youtube.com/embed/{v.group(1)}" if v.group(1) else f"https://player.vimeo.com/video/{v.group(2)}"
        parts.append(f'<div class="video"><iframe src="{src}" allowfullscreen loading="lazy"></iframe></div>')
    if p.get("summary"):
        parts.append(f'<p class="lead"><b>한 줄 요약</b> — {e(p["summary"])}</p>')
    if tip:
        parts.append(f'<div class="optip"><b>✍️ 운영자 한마디</b><p>{e(tip)}</p></div>')
    for s in p.get("sections") or []:
        parts.append(f'<h2>{e(s.get("heading", ""))}</h2><p>{e(s.get("body", ""))}</p>')  # 보강 섹션도 같은 모양
    if p.get("insight"):
        parts.append(f'<h2>💡 AI 해설 (실무 관점)</h2><blockquote>{e(p["insight"])}</blockquote>')
    faq = [f for f in p.get("faq") or [] if f.get("q")]
    if faq:
        parts.append("<h2>❓ 자주 묻는 질문</h2>" + "".join(
            f'<details><summary>Q. {e(f["q"])}</summary><p>{e(f.get("a", ""))}</p></details>' for f in faq))
    if p.get("videos"):
        parts.append('<h2>🎬 관련 튜토리얼</h2><div class="vids' + (" two" if len(p["videos"]) > 1 else "") + '">'
                     + "".join(yt_facade(v) for v in p["videos"]) + "</div>" + YT_JS)
    if p.get("refs"):
        parts.append('<h2>🔗 참고한 커뮤니티 토론</h2><ol class="refs">' + "".join(
            f'<li><a href="{e(r["url"])}" target="_blank" rel="noopener nofollow">{e(r["title"])}</a>'
            f' <span class="k">{e(r["source"])}' + (f' · 답글 {r["replies"]}' if r.get("replies") else "") + '</span></li>'
            for r in p["refs"]) + "</ol>")
    if related:
        parts.append("<h2>📚 함께 보면 좋은 글</h2><ul>" + "".join(
            f'<li><a href="{root}p/{r["id"]}.html">{e(r["title_ko"])}</a></li>' for r in related) + "</ul>")
    parts.append(newsletter_box(root))
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
    gstate = core.curation_state()  # 현황판 '기초 가이드 검토': 숨김은 제외, 검토 완료는 표시
    learn_guides = [g for g in _guides.load_all() if gstate.get("learn:" + g["id"]) != "hide"]
    tip_map = core.tips()
    for g in learn_guides:
        g["reviewed"] = gstate.get("learn:" + g["id"]) == "ok"
        g["tip"] = tip_map.get("learn:" + g["id"]) or g.get("tip", "")  # 현황판에서 쓴 팁이 우선, 없으면 가이드에 적힌 운영자 팁
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
    by_tool: dict[str, list] = defaultdict(list)
    for g in learn_guides:
        by_tool[g["tool"]].append(g)
    def learn_tile(t: str, gs: list[dict]) -> str:
        """홈 '도구별 기초 배우기' 상자: 대표 영상 썸네일(▶) + 가이드마다 작은 썸네일 — 글보다 영상을 선호하는 독자용."""
        lead = next((g for g in gs if g.get("videos")), gs[0])
        lv = (lead.get("videos") or [None])[0]
        hero = (f'<a class="lt-hero" href="{{ROOT}}{learn_url(lead)}" aria-label="{e(lead["title"])} 영상 가이드">'
                f'<img src="https://i.ytimg.com/vi/{e(lv["id"])}/mqdefault.jpg" alt="" loading="lazy">'
                f'<span class="lt-play" aria-hidden="true">▶</span><span class="lt-cap">{e(lead["title"].split(" — ")[0])}</span></a>'
                if lv else "")
        rows = "".join([
            f'<li><a href="{{ROOT}}{learn_url(g)}">'
            + (f'<img class="lt-th" src="https://i.ytimg.com/vi/{e(g["videos"][0]["id"])}/default.jpg" alt="" loading="lazy">'
               if g.get("videos") else '<span class="lt-th lt-ph" aria-hidden="true">📚</span>')
            + f'<span class="lt-t">{e(g["title"].split(" — ")[0])}</span>'
            + ('<span class="lt-v" title="영상 포함" aria-label="영상 포함">▶ 영상</span>' if g.get("videos") else "") + '</a></li>'
            for g in gs if g is not lead][:4])
        return (f'<div class="box lt"><h3><span aria-hidden="true">📚</span> <a href="{{ROOT}}learn/#{e(slug(t))}">{e(t)}</a>'
                f'<small class="n">{len(gs)}</small></h3>{hero}<ul class="lt-list">{rows}</ul>'
                f'<a class="more" href="{{ROOT}}{learn_url(gs[0])}">처음부터 배우기 →</a></div>')

    learn_tiles = "".join(learn_tile(t, gs) for t, gs in by_tool.items())
    home_head = (
        f'<section class="hero"><h1>3D 툴, 기초부터 <br>최신 소식까지 한곳에서</h1>'
        f'<p>3ds Max·Blender·Houdini·언리얼의 기본 기능을 <b>영상과 따라 하기</b>로 익히고, '
        f'전 세계 3D·VFX·AI 3D 소식은 매일 한국어로 정리해 둡니다.</p>'
        f'<div class="actions"><a class="btn primary" href="{{ROOT}}learn/">기초 가이드 시작하기</a>'
        f'<a class="btn ghost" href="{{ROOT}}weekly/">이번 주 요약 →</a></div>'
        f'<div class="stats"><span><b>{len(learn_guides)}</b>기초 가이드</span><span><b>{len(posts)}</b>정리된 소식</span>'
        f'<span><b>{tools_n}</b>도구 게시판</span><span><b>{len(weeks)}</b>주간 요약</span></div></section>'
        + (f'<h2 class="sec">도구별 기초 배우기 <a href="{{ROOT}}learn/">전체 보기 →</a></h2><div class="grid">{learn_tiles}</div>'
           if learn_tiles else "")
        + (f'<h2 class="sec">에디터 추천</h2><div class="cards">{"".join(card(p, "{ROOT}") for p in picks[:6])}</div>'
           if picks else "") +
        f'<h2 class="sec">분야별 소식 게시판</h2><div class="grid">{"".join(tiles)}</div>' +
        guide_sec +
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
            # 게시판 소개 2~3줄 (목록만 있는 '얇은 페이지' 방지): 도구별 정리 요약 → 없으면 유형·최근 주제로 구성
            kinds = ", ".join(t for t, ps in sorted(by_topic.items(), key=lambda kv: -len(kv[1])) if ps)
            tool_guides = [g for g in learn_guides if g["tool"].lower() in c.lower() or c.lower() in g["tool"].lower()]
            intro = (gd["intro"].split(". ")[0].rstrip(".") + "." if gd else
                     f"{c} 관련 소식 {len(items)}개를 모았습니다 ({kinds}).")
            intro_html = (f'<p class="desc">{e(intro)} 새 글은 매일 자동으로 정리되며, 아래 유형 버튼으로 '
                          f'업데이트·튜토리얼·플러그인만 골라 볼 수 있어요.'
                          + (f' 처음이라면 <a href="{{ROOT}}{learn_url(tool_guides[0])}">📚 {e(c)} 기초 가이드</a>부터 보세요.'
                             if tool_guides else "") + "</p>")
            board_pages(items, folder, "../../../", f"{d} › {c}",
                        f"<h1>{e(DOMAIN_ICON[d])} {e(d)} › {e(c)}</h1>" + intro_html + gd_link + tabs(c, "{ROOT}")
                        + chips(None), d)
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
    build_learn(learn_guides, posts)
    # 실무 파이프라인 (AI 3D 소식 → 작업 툴 스크립트)
    import recipes as _recipes
    recipes_ = [r for r in _recipes.load_all() if _recipes.published(r)]  # Blender 는 실행 검증 통과분만
    build_recipes(recipes_, posts)
    build_resources()
    build_showcase()

    # 저장한 글 (브라우저에만 저장 — static/user.js 가 그림)
    (OUT / "saved").mkdir(exist_ok=True)
    (OUT / "saved" / "index.html").write_text(page(
        f"저장한 글 - {SITE_TITLE}",
        '<div class="doc"><h1>☆ 저장한 글</h1><p class="desc">글·기초 가이드에서 <b>☆ 저장</b>을 누르면 여기에 모입니다. '
        '로그인 없이 <b>이 브라우저에만</b> 저장돼요 (다른 기기와는 공유되지 않음).</p></div>'
        '<div class="board" id="saved-list"></div>', "../", extra_head='<meta name="robots" content="noindex">'),
        encoding="utf-8")

    # 404 페이지 (GitHub Pages 가 없는 주소에 이 파일을 보여줌 → 어느 경로에서든 동작하도록 절대 경로)
    abs_root = "/" + BASE_URL.split("://", 1)[1].split("/", 1)[1].strip("/") + "/"
    nf = (f'<div class="doc"><h1>페이지를 찾을 수 없어요</h1><p class="desc">주소가 바뀌었거나 삭제된 글일 수 있습니다. '
          f'위 검색창에 도구 이름(예: Blender, 3ds Max)이나 기능(예: Bend)을 입력해 보세요.</p>'
          f'<div class="actions"><a class="btn primary" href="{abs_root}">홈으로</a> '
          f'<a class="btn ghost" href="{abs_root}learn/">기초 가이드</a> <a class="btn ghost" href="{abs_root}weekly/">주간 요약</a></div></div>'
          f'<h2 class="sec">많이 본 글</h2><div class="cards">{"".join(card(q, abs_root) for q in popular(posts, 6))}</div>')
    (OUT / "404.html").write_text(page(f"페이지를 찾을 수 없어요 - {SITE_TITLE}", nf, abs_root,
                                       extra_head='<meta name="robots" content="noindex">'), encoding="utf-8")

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
               + ("이름·연락처 등 개인정보를 직접 수집하지 않습니다. 단, 뉴스레터를 구독하는 경우에만 아래와 같이 이메일 주소를 받습니다.</p>"
                  "<h2>뉴스레터</h2><ul><li>수집 항목: 이메일 주소 (구독 시 본인이 직접 입력)</li>"
                  "<li>목적: 주간 3D 소식·가이드 뉴스레터 발송</li><li>보관 기간: 수신거부(구독 해지) 시까지, 해지 즉시 발송 중단</li>"
                  "<li>처리 위탁: Buttondown (뉴스레터 발송 서비스) — 구독 확인 메일을 거친 경우에만 발송</li>"
                  "<li>수신거부: 모든 메일 하단의 구독 해지 링크 또는 아래 문의 메일</li>"
                  "<li>다른 곳에서 수집한 이메일로는 보내지 않으며, 제3자에게 제공하지 않습니다.</li></ul><p>"
                  if cfg.get("newsletter") else "이름·연락처 등 개인정보를 직접 수집하지 않습니다.</p><p>")
               + "</p>"
               f"<h2>방문 통계</h2><p>{'방문 통계를 위해 GoatCounter 를 사용합니다. 쿠키를 사용하지 않으며 개인을 식별하지 않는 '
                                   '집계(페이지 조회수, 유입 경로, 브라우저 종류 등)만 수집합니다.' if cfg['goatcounter'] else '현재 별도의 방문 통계 도구를 사용하지 않습니다.'}</p>"
               f"<h2>광고</h2><p>사이트는 Google AdSense 등 제3자 광고를 게재할 수 있습니다. Google 을 비롯한 제3자 공급업체는 "
               f"쿠키를 사용해 사용자의 이전 방문 기록을 바탕으로 광고를 게재할 수 있으며, 사용자는 "
               f'<a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 '
               f"맞춤 광고를 해제할 수 있습니다. 자세한 내용은 "
               f'<a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener">Google 광고 정책</a>을 참고하세요.</p>'
               f"<h2>문의</h2><p>개인정보·저작권 관련 문의: {mail_link('[3dflowhub] 개인정보·저작권 문의')}</p>"
               f"<p class=\"crumb\">시행일: 2026-10-16 · 개정: 2026-10-19 (뉴스레터 항목)</p></article>")
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
    # 검색 인덱스: 글(p) + 기초 가이드(g) + 도구별 정리(r). o = 원문 영어 제목(영어 검색용)
    index = [{"u": f"p/{p['id']}.html", "k": "p", "t": p["title_ko"], "o": p.get("title", "")[:120],
              "c": f'{p["domain"]} › {p.get("category") or ""}', "g": " ".join(p.get("tags") or [])} for p in posts]
    index += [{"u": learn_url(g), "k": "g", "t": g["title"], "o": f"{g['tool']} {g['name']}",
               "c": f"{g['tool']} › {g['group']}", "g": " ".join(g.get("related") or [])} for g in learn_guides]
    index += [{"u": guide_url(r["domain"], r["tool"]), "k": "r", "t": r["title"], "o": r["tool"],
               "c": f"{r['domain']} › {r['tool']}", "g": ""} for r in roundups]
    index += [{"u": f"recipes/{r['id']}/", "k": "r", "t": r["title"], "o": f"{r['host']} {r['category']}",
               "c": f"{r['category']} → {r['host']}", "g": ""} for r in recipes_]
    # 한글↔영문 도구 이름 (용어집): '블렌더' 로 찾아도 'Blender' 제목이 제목 일치로 잡히도록
    alias: dict[str, str] = {}
    for canon, (_rx, ko) in core.GLOSSARY.items():
        if ko:
            alias[ko.lower()] = canon.lower()
            alias[ko.replace(" ", "").lower()] = canon.lower()
            alias[canon.lower()] = ko.lower()
    (OUT / "search.json").write_text(json.dumps({"a": alias, "i": index}, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
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
           [f"{BASE_URL}/resources/", f"{BASE_URL}/showcase/"] + [f"{BASE_URL}/recipes/"] + [f"{BASE_URL}/recipes/{r['id']}/" for r in recipes_] + \
           [f"{BASE_URL}/p/{p['id']}.html" for p in posts if not is_thin(p)]
    # 수정일 신호: 글은 수집일, 가이드는 작성일 (Google 이 다시 크롤할 페이지를 고를 때 사용)
    lastmod = {f"{BASE_URL}/p/{p['id']}.html": (p.get("collected_at") or "")[:10] for p in posts}
    lastmod.update({f"{BASE_URL}/{learn_url(g)}": (g.get("at") or "")[:10] for g in learn_guides})
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/'
                                     'schemas/sitemap/0.9">' + "".join(
                                         f"<url><loc>{e(u)}</loc>" + (f"<lastmod>{lastmod[u]}</lastmod>" if lastmod.get(u) else "")
                                         + "</url>" for u in urls)
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
