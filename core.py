"""
3dflowhub core pipeline
=======================
[1] 동적 키워드 생성 → [2] 크롤링/수집 → [3] LLM 요약·분류 → Notion 저장
→ [4] 티스토리 발행(+광고 자동 삽입) → [5] memory.json 성찰 기록

------------------------------------------------------------------------------
■ 사전 설정 가이드
------------------------------------------------------------------------------
환경변수 (로컬: .env / GitHub Actions: Settings → Secrets and variables → Actions)

  LLM_API_KEY           OpenAI 호환 LLM API 키 (기본: Google AI Studio 무료 키 https://aistudio.google.com/apikey)
  LLM_BASE_URL          기본 https://generativelanguage.googleapis.com/v1beta/openai
                        (Groq: https://api.groq.com/openai/v1 , OpenRouter: https://openrouter.ai/api/v1)
  LLM_MODEL             기본 "gemini-flash-lite-latest"
  NOTION_TOKEN          https://www.notion.so/my-integrations 에서 Internal Integration 생성
  NOTION_DATABASE_ID    eba32801b6b141e2849ce85f819c3ea4
                        ※ DB 페이지 우측 상단 ··· → 연결(Connections) → 통합 추가 필수
  TISTORY_ACCESS_TOKEN  티스토리 Open API Access Token
  TISTORY_BLOG_NAME     hjh1014   (hjh1014.tistory.com 의 앞부분)
  TISTORY_VISIBILITY    0=비공개(초안), 3=발행  (기본 0 — 검수 후 공개 권장)
  TISTORY_CATEGORY_MAP  JSON, 예: {"3D DCC":"123","Game Engine":"124","VFX":"125","AI 3D":"126"}
                        (카테고리 ID는 /apis/category/list 로 조회)
  ADSENSE_CLIENT        ca-pub-XXXXXXXXXXXXXXXX
  ADSENSE_SLOT          1234567890
  AD_HTML               (선택) 애드센스 대신 쓸 커스텀 배너 HTML

티스토리 토큰 발급 (OAuth 2.0 Authorization Code)
  1. https://www.tistory.com/guide/api/manage/register 에서 앱 등록
     - CallBack: 예) https://hjh1014.tistory.com
  2. 브라우저로 접속:
     https://www.tistory.com/oauth/authorize?client_id={APP_ID}&redirect_uri={CALLBACK}&response_type=code
  3. 리다이렉트된 URL의 ?code=... 값 복사
  4. GET https://www.tistory.com/oauth/access_token?client_id={APP_ID}
         &client_secret={SECRET}&redirect_uri={CALLBACK}&code={CODE}&grant_type=authorization_code
     → 응답의 access_token 을 TISTORY_ACCESS_TOKEN 에 저장

⚠ 중요: 티스토리는 2024년 2월 Open API 신규 등록/서비스를 종료했습니다.
  기존에 발급된 토큰이 없다면 API 호출은 실패합니다. 이 경우 본 모듈은
  파이프라인을 멈추지 않고 output/tistory_drafts/*.html 로 광고가 삽입된
  완성 HTML을 저장합니다 → 티스토리 에디터 'HTML 모드'에 붙여넣기만 하면 됩니다.

애드센스 주의: 티스토리 블로그에 '애드센스 플러그인'을 이미 켜 두었다면 본문 광고와
  중복될 수 있으니 AD_POSITIONS 로 위치를 조정하세요. 무효 클릭 정책상 한 글에 3개 이하 권장.
------------------------------------------------------------------------------
"""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from notion_client import Client as NotionClient
except ImportError:  # 대시보드만 띄우는 환경 대비
    NotionClient = None

log = logging.getLogger("3dflowhub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─────────────────────────── 설정 ───────────────────────────
ROOT = Path(__file__).parent
MEMORY_PATH = ROOT / "memory" / "memory.json"
PUBLISHED_LOG = ROOT / "memory" / "published.json"
DRAFT_DIR = ROOT / "output" / "tistory_drafts"

# GitHub Models 는 2026-07-30 서비스 종료 → OpenAI 호환 무료 API 사용 (기본: Google Gemini 무료 티어)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENDPOINT = (os.getenv("LLM_BASE_URL") or
                "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/") + "/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL") or "gemini-flash-lite-latest"  # Actions 에서 빈 변수는 "" 로 전달됨

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "eba32801b6b141e2849ce85f819c3ea4")

TISTORY_API = "https://www.tistory.com/apis/post/write"
TISTORY_ACCESS_TOKEN = os.getenv("TISTORY_ACCESS_TOKEN", "")
TISTORY_BLOG_NAME = os.getenv("TISTORY_BLOG_NAME", "hjh1014")
TISTORY_VISIBILITY = os.getenv("TISTORY_VISIBILITY", "0")
TISTORY_CATEGORY_MAP: dict = json.loads(os.getenv("TISTORY_CATEGORY_MAP", "{}") or "{}")

ADSENSE_CLIENT = os.getenv("ADSENSE_CLIENT", "")
ADSENSE_SLOT = os.getenv("ADSENSE_SLOT", "")
AD_HTML = os.getenv("AD_HTML", "")
AD_POSITIONS = ("top", "middle", "bottom")
TISTORY_EMBED_IMAGES = os.getenv("TISTORY_EMBED_IMAGES", "1") == "1"  # 원문 대표 이미지 + 출처 표기 (끄려면 0)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (3dflowhub curator; +https://github.com/HEO-J-H/3dflowhub)"}

# 도메인 매뉴얼: 시드 키워드 + 고정 RSS
DOMAINS: dict[str, dict] = {
    "3D DCC": {
        "seeds": ["3ds Max", "Blender", "Maya", "V-Ray", "Corona Renderer"],
        "feeds": ["https://www.cgchannel.com/feed/", "https://www.blendernation.com/feed/",
                  "https://www.blender.org/feed/", "https://code.blender.org/feed/"],
    },
    "Game Engine": {
        "seeds": ["Unreal Engine 5", "Unity 6", "Nanite", "Lumen", "Godot"],
        "feeds": ["https://www.unrealengine.com/en-US/rss", "https://blog.unity.com/feed"],
    },
    "VFX": {
        "seeds": ["After Effects", "Houdini", "Nuke", "motion graphics"],
        "feeds": ["https://www.fxguide.com/feed/", "https://motionographer.com/feed/"],
    },
    "AI 3D": {
        "seeds": ["Gaussian Splatting", "NeRF", "text-to-3D", "3D generative AI"],
        "feeds": ["https://80.lv/feed", "https://www.cgchannel.com/category/news/ai/feed/",
                  "https://blogs.nvidia.com/blog/category/generative-ai/feed/",
                  # arXiv 최신 논문 (가우시안 스플래팅 / NeRF / text-to-3D)
                  "https://export.arxiv.org/api/query?search_query=abs:%22gaussian+splatting%22+OR+abs:%22text-to-3D%22"
                  "+OR+abs:%22neural+radiance+field%22&sortBy=submittedDate&sortOrder=descending&max_results=15"],
    },
}


# 세부 카테고리 시드 — LLM 이 새 카테고리를 제안하면 memory.json["categories"] 에 자동 추가된다
SEED_CATEGORIES: dict[str, list[str]] = {
    "3D DCC": ["모델링", "렌더링", "텍스처링", "애니메이션", "툴 업데이트"],
    "Game Engine": ["엔진 업데이트", "게임 개발 사례", "튜토리얼", "신작 게임"],
    "VFX": ["시뮬레이션", "컴포지팅", "모션그래픽", "제작 사례"],
    "AI 3D": ["3D 생성 AI", "가우시안·NeRF", "AI 도구", "연구·논문"],
}
MAX_CATEGORIES_PER_DOMAIN = 10  # 카테고리 난립 방지
MAX_AGE_DAYS = 30  # 이보다 오래된 기사는 수집하지 않음


# ─────────────────────────── 유틸 / 메모리 ───────────────────────────
def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().rstrip("/").encode()).hexdigest()[:16]


def load_memory() -> dict:
    return _load_json(MEMORY_PATH, {"runs": [], "good_keywords": [], "bad_keywords": [], "lessons": []})


# ─────────────────────────── LLM (OpenAI 호환) ───────────────────────────
def llm(prompt: str, system: str = "You are a concise assistant.", max_tokens: int = 800,
        json_mode: bool = False) -> str:
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY 미설정")
    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    errors = []
    for use_json in ((True, False) if json_mode else (False,)):  # JSON 모드 미지원 시 일반 모드 재시도
        payload = {**body, **({"response_format": {"type": "json_object"}} if use_json else {})}
        try:
            for attempt in range(4):  # 429/5xx(무료 한도·일시 장애)는 지수 백오프 재시도
                r = requests.post(LLM_ENDPOINT, json=payload, timeout=60, headers=headers)
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
                wait = float(r.headers.get("retry-after") or 0) or 5 * 2 ** attempt
                log.info("LLM %s — %.0f초 후 재시도", r.status_code, wait)
                time.sleep(min(wait, 60))
            data = r.json() if r.ok else None
            if data and data.get("choices"):
                return (data["choices"][0]["message"].get("content") or "").strip()
            errors.append(f"{r.status_code} json={use_json}: {r.text[:200]!r}")
        except (requests.RequestException, ValueError) as e:
            errors.append(f"json={use_json}: {type(e).__name__} {e}"[:200])
    raise RuntimeError(" | ".join(errors))


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


# ─────────────────────────── [1] 동적 키워드 ───────────────────────────
def generate_keywords(domains: list[str], per_domain: int = 2) -> dict[str, list[str]]:
    """memory.json 의 성공/실패 키워드를 컨텍스트로 주입해 키워드를 조합."""
    mem = load_memory()
    result: dict[str, list[str]] = {}
    for d in domains:
        seeds = DOMAINS[d]["seeds"]
        prompt = (
            f"Domain: {d}\nSeed terms: {', '.join(seeds)}\n"
            f"Keywords that worked before: {', '.join(mem['good_keywords'][-10:]) or 'none'}\n"
            f"Keywords that failed: {', '.join(mem['bad_keywords'][-10:]) or 'none'}\n"
            f"Today: {datetime.now():%Y-%m-%d}\n"
            f"Return JSON {{\"keywords\": [...]}} with {per_domain} English search queries "
            f"for the latest news or tutorials in this domain."
        )
        try:
            kws = _parse_json(llm(prompt, max_tokens=150, json_mode=True)).get("keywords", [])
        except Exception as e:  # LLM 실패 시 시드로 폴백
            log.warning("키워드 생성 실패(%s) → 시드 사용: %s", d, e)
            kws = []
        result[d] = [k for k in kws if isinstance(k, str)][:per_domain] or seeds[:per_domain]
    return result


# ─────────────────────────── [2] 수집 ───────────────────────────
def _google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}+when:7d&hl=en-US&gl=US&ceid=US:en"


VIDEO_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})|player\.vimeo\.com/video/(\d+)")


def extract_media(soup: BeautifulSoup, base_url: str) -> dict:
    """대표 이미지(og:image)와 첫 번째 YouTube/Vimeo 영상 URL."""
    def meta(*names: str) -> str:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    image = meta("og:image", "og:image:url", "twitter:image")
    if not image:  # 메타 태그가 없으면 본문 첫 이미지
        img = (soup.find("article") or soup).find("img", src=True)
        image = img["src"] if img else ""
    image = urljoin(base_url, image) if image else ""
    video = ""
    candidates = [meta("og:video", "og:video:url", "twitter:player")]
    candidates += [f.get("src", "") for f in soup.find_all("iframe")]
    candidates += [a["href"] for a in soup.find_all("a", href=True)][:300]
    for c in candidates:
        m = VIDEO_RE.search(c or "")
        if m:
            video = (f"https://www.youtube.com/watch?v={m.group(1)}" if m.group(1)
                     else f"https://vimeo.com/{m.group(2)}")
            break
    if not image.startswith("http") and video and (m := VIDEO_RE.search(video)) and m.group(1):
        image = f"https://img.youtube.com/vi/{m.group(1)}/hqdefault.jpg"  # 대표 이미지 없으면 유튜브 썸네일
    return {"image": image if image.startswith("http") else "", "video": video}


def fetch_article(url: str, limit: int = 4000) -> tuple[str, dict]:
    """본문 텍스트와 미디어(대표 이미지/영상)를 함께 수집."""
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        media = extract_media(soup, r.url)
        for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            t.decompose()
        node = soup.find("article") or soup.body or soup
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        return text[:limit], media
    except Exception as e:
        log.debug("본문 수집 실패 %s: %s", url, e)
        return "", {"image": "", "video": ""}


def fetch_article_text(url: str, limit: int = 4000) -> str:
    return fetch_article(url, limit)[0]


def collect(domains: list[str], max_items: int, seen: set[str]) -> list[dict]:
    keywords = generate_keywords(domains)
    candidates: list[dict] = []
    for d in domains:
        sources = DOMAINS[d]["feeds"] + [_google_news_rss(k) for k in keywords[d]]
        for src in sources:
            try:
                feed = feedparser.parse(src, request_headers=HTTP_HEADERS)
            except Exception as e:
                log.warning("피드 실패 %s: %s", src, e)
                continue
            if not feed.entries:
                RUN_ERRORS.append(f"empty feed: {src}")
            for e in feed.entries[:10]:
                link = e.get("link", "")
                if not link or url_hash(link) in seen:
                    continue
                published = e.get("published_parsed") or e.get("updated_parsed")
                if published and (time.time() - calendar.timegm(published)) > MAX_AGE_DAYS * 86400:
                    continue  # 오래된 기사 제외
                seen.add(url_hash(link))
                candidates.append({
                    "title": e.get("title", "").strip(),
                    "url": link,
                    "hint_domain": d,
                    "rss_summary": BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ")[:800],
                })
    # 도메인 균형을 맞추어 max_items 개 선택 (라운드로빈)
    picked, by_dom = [], {d: [c for c in candidates if c["hint_domain"] == d] for d in domains}
    while len(picked) < max_items and any(by_dom.values()):
        for d in domains:
            if by_dom[d] and len(picked) < max_items:
                picked.append(by_dom[d].pop(0))
    log.info("수집 후보 %d건 → 선택 %d건", len(candidates), len(picked))
    return picked


# ─────────────────────────── [3] LLM 요약·분류 ───────────────────────────
SUMMARY_SYSTEM = (
    "You are an editor for a Korean 3D/VFX/game-engine/AI-3D tech blog. "
    "Write in natural Korean. Never invent facts not in the source."
)


RUN_ERRORS: list[str] = []  # 이번 실행의 실패 사유 (memory.json 에 기록)


def load_categories() -> dict[str, list[str]]:
    saved = load_memory().get("categories", {})
    return {d: list(dict.fromkeys(SEED_CATEGORIES.get(d, []) + saved.get(d, []))) for d in DOMAINS}


def register_category(domain: str, category: str) -> str:
    """세부 카테고리 확정. 새 이름이면 memory.json 에 추가 (도메인당 최대 개수 초과 시 첫 카테고리로 대체)."""
    category = re.sub(r"[/|<>,]", "·", (category or "").strip())[:15]
    cats = load_categories()[domain]
    if not category:
        return cats[0]
    if category in cats:
        return category
    if len(cats) >= MAX_CATEGORIES_PER_DOMAIN:
        return cats[0]
    mem = load_memory()
    mem.setdefault("categories", {}).setdefault(domain, []).append(category)
    _save_json(MEMORY_PATH, mem)
    log.info("새 카테고리 추가: %s / %s", domain, category)
    return category


def summarize(item: dict) -> dict | None:
    body, media = fetch_article(item["url"])
    if len(body) < 200:  # 본문 크롤링 실패 시 RSS 요약으로 대체
        body = f"{item['title']}\n{item['rss_summary']}"
    if len(body) < 80:
        log.info("본문 부족으로 건너뜀: %s", item["url"])
        RUN_ERRORS.append("short body")
        return None
    prompt = (
        f"Title: {item['title']}\nURL: {item['url']}\nContent:\n{body}\n\n"
        f"Existing categories per domain: {json.dumps(load_categories(), ensure_ascii=False)}\n"
        "Return JSON with keys:\n"
        ' "title_ko": catchy Korean title (<=60 chars),\n'
        ' "domain": one of ["3D DCC","Game Engine","VFX","AI 3D"],\n'
        ' "category": best matching existing category of that domain; only if none fits, '
        'a new short Korean category name (<=10 chars),\n'
        ' "tags": 3-6 short tags,\n'
        ' "summary": one-sentence Korean summary,\n'
        ' "insight": 3-5 sentences of ORIGINAL Korean commentary for Korean 3D/VFX/game artists — why it matters, '
        'how to apply it in practice, who should care. Do not restate the article,\n'
        ' "sections": list of 3-5 objects {"heading": str, "body": str} in Korean (each body 2-4 sentences)'
    )
    try:
        data = _parse_json(llm(prompt, system=SUMMARY_SYSTEM, max_tokens=1200, json_mode=True))
    except Exception as e:
        log.warning("요약 실패 %s: %s", item["url"], e)
        RUN_ERRORS.append(f"summarize: {str(e)[:600]}")
        return None
    if not data.get("sections"):
        log.warning("LLM 응답에 sections 없음: %s", item["url"])
        RUN_ERRORS.append(f"no sections: {str(data)[:200]}")
        return None
    if data.get("domain") not in DOMAINS:
        data["domain"] = item["hint_domain"]
    data["category"] = register_category(data["domain"], data.get("category", ""))
    if isinstance(data.get("tags"), str):
        data["tags"] = [t.strip() for t in data["tags"].split(",") if t.strip()]
    return {**item, **data, "media": media, "collected_at": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────── Notion ───────────────────────────
def _notion() -> "NotionClient | None":
    if not (NOTION_TOKEN and NotionClient):
        return None
    return NotionClient(auth=NOTION_TOKEN, notion_version="2022-06-28")  # properties 기반 API 고정


NOTION_SCHEMA = {
    "URL": {"url": {}},
    "Domain": {"select": {"options": [{"name": d} for d in DOMAINS]}},
    "Category": {"select": {}},
    "Tags": {"multi_select": {}},
    "Summary": {"rich_text": {}},
    "Thumbnail": {"files": {}},
    "Video": {"url": {}},
    "Status": {"select": {"options": [{"name": "Collected", "color": "gray"},
                                      {"name": "Published", "color": "green"}]}},
    "TistoryURL": {"url": {}},
    "CollectedAt": {"date": {}},
}


def ensure_notion_schema(client) -> None:
    """DB에 필요한 속성이 없으면 자동 생성하고, 제목 속성 이름을 'Name'으로 맞춘다."""
    if client is None:
        return
    try:
        # 스키마 변경은 최신 data source API(2025-09-03)로 해야 실제 반영된다
        new = NotionClient(auth=NOTION_TOKEN)
        ds_id = new.databases.retrieve(database_id=NOTION_DATABASE_ID)["data_sources"][0]["id"]
        props = new.request(path=f"data_sources/{ds_id}", method="GET")["properties"]
        update: dict = {}
        title_name = next((n for n, p in props.items() if p["type"] == "title"), None)
        if title_name and title_name != "Name":
            update[title_name] = {"name": "Name"}
        for name, spec in NOTION_SCHEMA.items():
            if name not in props:
                update[name] = spec
            elif props[name]["type"] != next(iter(spec)):
                log.warning("Notion 속성 '%s' 타입이 %s 입니다 (필요: %s) — 직접 수정 필요",
                            name, props[name]["type"], next(iter(spec)))
        if update:
            new.request(path=f"data_sources/{ds_id}", method="PATCH", body={"properties": update})
            log.info("Notion DB 속성 생성/수정: %s", ", ".join(update))
    except Exception as e:
        log.error("Notion 스키마 설정 실패 (통합 연결 여부 확인): %s", e)


def _query_db(client, body: dict) -> dict:
    # notion-client 2.7+ 에서 databases.query 가 제거되어 REST 직접 호출
    return client.request(path=f"databases/{NOTION_DATABASE_ID}/query", method="POST", body=body)


def notion_existing_urls(client) -> set[str]:
    """Notion DB에 이미 있는 URL 해시 (중복 방지 1차)."""
    seen, cursor = set(), None
    try:
        while True:
            res = _query_db(client, {"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            for p in res["results"]:
                u = p["properties"].get("URL", {}).get("url")
                if u:
                    seen.add(url_hash(u))
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
    except Exception as e:
        log.warning("Notion 조회 실패: %s", e)
    return seen


def _rt(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[:1990]}}]


def save_to_notion(client, item: dict) -> str | None:
    """Notion DB 속성: Name(title) URL(url) Domain(select) Tags(multi_select)
    Summary(rich_text) Status(select) TistoryURL(url) CollectedAt(date)"""
    if client is None:
        return None
    media = item.get("media") or {}
    children = []
    if media.get("image"):
        children.append({"object": "block", "type": "image",
                         "image": {"type": "external", "external": {"url": media["image"]}}})
    if media.get("video"):
        children.append({"object": "block", "type": "video",
                         "video": {"type": "external", "external": {"url": media["video"]}}})
    if item.get("insight"):
        children.append({"object": "block", "type": "callout",
                         "callout": {"rich_text": _rt(item["insight"]), "icon": {"type": "emoji", "emoji": "💡"}}})
    for s in item["sections"]:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rt(s["heading"])}})
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(s["body"])}})
    try:
        page = client.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={
                "Name": {"title": _rt(item["title_ko"])},
                "URL": {"url": item["url"]},
                "Domain": {"select": {"name": item["domain"]}},
                **({"Category": {"select": {"name": item["category"]}}} if item.get("category") else {}),
                "Tags": {"multi_select": [{"name": t[:50].replace(",", " ")} for t in item.get("tags", [])]},
                **({"Thumbnail": {"files": [{"name": "thumbnail", "type": "external",
                                             "external": {"url": media["image"]}}]}} if media.get("image") else {}),
                **({"Video": {"url": media["video"]}} if media.get("video") else {}),
                "Summary": {"rich_text": _rt(item.get("summary", ""))},
                "Status": {"select": {"name": "Collected"}},
                "CollectedAt": {"date": {"start": item["collected_at"]}},
            },
            children=children,
            **({"cover": {"type": "external", "external": {"url": media["image"]}}} if media.get("image") else {}),
        )
        return page["id"]
    except Exception as e:
        log.error("Notion 저장 실패 %s: %s", item["url"], e)
        return None


def backfill_notion(client, limit: int = 100) -> int:
    """카테고리/이미지가 없는 기존 노션 글을 보강 (원문에서 미디어 재수집, LLM 으로 세부 카테고리 분류)."""
    done = 0
    res = _query_db(client, {"page_size": min(limit, 100),
                             "filter": {"property": "Category", "select": {"is_empty": True}}})
    for p in res["results"]:
        pr = p["properties"]
        title = "".join(t["plain_text"] for t in pr["Name"]["title"])
        domain = (pr["Domain"]["select"] or {}).get("name") or "3D DCC"
        summary = "".join(t["plain_text"] for t in pr["Summary"]["rich_text"])
        url = pr["URL"]["url"] or ""
        try:
            cats = load_categories()[domain]
            out = _parse_json(llm(
                f"Title: {title}\nSummary: {summary}\nDomain: {domain}\nCategories: {cats}\n"
                'Return JSON {"category": "best existing category, or a new short Korean name (<=10 chars) '
                'only if none fits"}', max_tokens=100, json_mode=True))
            category = register_category(domain, out.get("category", ""))
            media = fetch_article(url)[1] if url else {}
            props = {"Category": {"select": {"name": category}}}
            if media.get("image"):
                props["Thumbnail"] = {"files": [{"name": "thumbnail", "type": "external",
                                                 "external": {"url": media["image"]}}]}
            if media.get("video"):
                props["Video"] = {"url": media["video"]}
            client.pages.update(page_id=p["id"], properties=props,
                                **({"cover": {"type": "external", "external": {"url": media["image"]}}}
                                   if media.get("image") else {}))
            done += 1
            log.info("보강: %s → %s", title[:30], category)
        except Exception as e:
            log.warning("보강 실패 %s: %s", title[:30], e)
    return done


def mark_notion_published(client, page_id: str | None, post_url: str) -> None:
    if not (client and page_id):
        return
    try:
        client.pages.update(page_id=page_id, properties={
            "Status": {"select": {"name": "Published"}},
            "TistoryURL": {"url": post_url or None},
        })
    except Exception as e:
        log.warning("Notion 상태 업데이트 실패: %s", e)


# ─────────────────────────── 광고 삽입 ───────────────────────────
def ad_banner_html(position: str) -> str:
    """애드센스(또는 AD_HTML 커스텀 배너) 블록. 미설정이면 빈 문자열."""
    if AD_HTML:
        inner = AD_HTML
    elif ADSENSE_CLIENT and ADSENSE_SLOT:
        inner = (
            f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT}" '
            f'crossorigin="anonymous"></script>'
            f'<ins class="adsbygoogle" style="display:block" data-ad-client="{ADSENSE_CLIENT}" '
            f'data-ad-slot="{ADSENSE_SLOT}" data-ad-format="auto" data-full-width-responsive="true"></ins>'
            f"<script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>"
        )
    else:
        return ""
    return f'\n<div class="flowhub-ad flowhub-ad-{position}" style="margin:24px 0;text-align:center;">{inner}</div>\n'


def _section_html(s: dict) -> str:
    return f"<h2>{html.escape(s['heading'])}</h2>\n<p>{html.escape(s['body'])}</p>\n"


def image_figure(src: str, source_url: str, alt: str = "") -> str:
    """원문 대표 이미지 + 출처 표기 캡션 (이미지는 원저작자 소유, 원문으로 링크)."""
    site = re.sub(r"^www\.", "", urlparse(source_url).netloc) or "원문"
    return (f'<figure style="margin:0 0 16px;text-align:center;">'
            f'<a href="{html.escape(source_url)}" target="_blank" rel="noopener nofollow">'
            f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" referrerpolicy="no-referrer" '
            f'style="max-width:100%;height:auto;"/></a>'
            f'<figcaption style="color:#888;font-size:0.85em;margin-top:6px;">'
            f'이미지 출처: <a href="{html.escape(source_url)}" target="_blank" rel="noopener nofollow">'
            f'{html.escape(site)}</a> (원저작자에게 저작권이 있습니다)</figcaption></figure>\n')


def build_post_html(item: dict) -> str:
    """intro + [AD top] + part_1 + [AD middle] + part_2 + source + [AD bottom]"""
    sections = item["sections"]
    mid = max(1, len(sections) // 2)
    part_1 = "".join(_section_html(s) for s in sections[:mid])
    part_2 = "".join(_section_html(s) for s in sections[mid:])

    media = item.get("media") or {}
    hero = ""
    # 원문 대표 이미지는 출처 표기와 원문 링크를 함께 넣는다 (TISTORY_EMBED_IMAGES=0 으로 끌 수 있음)
    if media.get("image") and TISTORY_EMBED_IMAGES:
        hero += image_figure(media["image"], item["url"], item.get("title_ko", ""))
    vid = VIDEO_RE.search(media.get("video", ""))
    if vid:
        src = (f"https://www.youtube.com/embed/{vid.group(1)}" if vid.group(1)
               else f"https://player.vimeo.com/video/{vid.group(2)}")
        hero += (f'<div style="position:relative;padding-top:56.25%;margin:16px 0;">'
                 f'<iframe src="{src}" style="position:absolute;top:0;left:0;width:100%;height:100%;" '
                 f'frameborder="0" allowfullscreen></iframe></div>\n')
    label = item["domain"] + (f" › {item['category']}" if item.get("category") else "")
    intro = (hero + f'<p style="font-size:1.05em;"><b>한 줄 요약</b> — {html.escape(item.get("summary", ""))}</p>\n'
             f'<p style="color:#888;">분류: {html.escape(label)}</p>\n')
    if item.get("insight"):
        part_2 += (f'<h2>💡 에디터 코멘트</h2>\n<blockquote style="border-left:4px solid #4a90e2;padding:8px 14px;">'
                   f'{html.escape(item["insight"])}</blockquote>\n')
    source = (f'<hr/><p>원문:<a href="{html.escape(item["url"])}" target="_blank" rel="noopener nofollow">'
              f'{html.escape(item["title"])}</a></p>\n'
              f'<p style="color:#999;font-size:0.85em;">본 글은 3dflowhub가 원문을 요약·번역한 큐레이션 콘텐츠입니다.</p>\n')

    ad = {p: (ad_banner_html(p) if p in AD_POSITIONS else "") for p in ("top", "middle", "bottom")}
    return intro + ad["top"] + part_1 + ad["middle"] + part_2 + source + ad["bottom"]


# ─────────────────────────── [4] 티스토리 발행 ───────────────────────────
def _published() -> dict:
    return _load_json(PUBLISHED_LOG, {})


def _save_draft_file(item: dict, content: str) -> str:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{url_hash(item['url'])}.html"
    header = (f"<!-- TITLE: {item['title_ko']} | TAGS: {','.join(item.get('tags', []))} "
              f"| CATEGORY: {item['domain']}/{item.get('category', '')} | NOTION: {item.get('notion_id', '')} -->")
    path.write_text(f"{header}\n{content}", encoding="utf-8")
    return str(path)


def publish_to_tistory(item: dict) -> dict:
    """티스토리에 발행. 실패해도 예외를 던지지 않고 결과 dict 를 반환.

    return: {"status": "published"|"duplicate"|"draft_file"|"error", "url": str, "detail": str}
    """
    key = url_hash(item["url"])
    log_db = _published()
    if key in log_db:  # 중복 발행 방지 (2차, 발행 기록 기준)
        return {"status": "duplicate", "url": log_db[key].get("post_url", ""), "detail": "already published"}

    content = build_post_html(item)
    result = {"status": "error", "url": "", "detail": ""}

    if TISTORY_ACCESS_TOKEN:
        data = {
            "access_token": TISTORY_ACCESS_TOKEN,
            "output": "json",
            "blogName": TISTORY_BLOG_NAME,
            "title": item["title_ko"],
            "content": content,
            "visibility": TISTORY_VISIBILITY,
            "tag": ",".join(item.get("tags", [])),
        }
        if cat := TISTORY_CATEGORY_MAP.get(item["domain"]):
            data["category"] = cat
        try:
            r = requests.post(TISTORY_API, data=data, timeout=30)
            r.raise_for_status()
            ts = r.json().get("tistory", {})
            if str(ts.get("status")) == "200":
                result = {"status": "published", "url": ts.get("url", ""), "detail": f"postId={ts.get('postId')}"}
            else:
                result["detail"] = f"API status={ts.get('status')} {ts.get('error_message', '')}"
        except Exception as e:
            result["detail"] = f"{type(e).__name__}: {e}"
        if result["status"] != "published":
            log.error("티스토리 발행 실패 [%s]: %s", item["title_ko"], result["detail"])
    else:
        result["detail"] = "TISTORY_ACCESS_TOKEN 미설정"

    # API 실패/미설정 → 붙여넣기용 HTML 초안 파일로 폴백
    if result["status"] != "published":
        result = {"status": "draft_file", "url": _save_draft_file(item, content), "detail": result["detail"]}

    log_db[key] = {"title": item["title_ko"], "source": item["url"], "status": result["status"],
                   "post_url": result["url"], "at": datetime.now(timezone.utc).isoformat()}
    _save_json(PUBLISHED_LOG, log_db)
    return result


# ─────────────────────────── [5] 성찰 기록 ───────────────────────────
def reflect(stats: dict, keywords_used: list[str]) -> None:
    mem = load_memory()
    mem["runs"] = (mem["runs"] + [stats])[-50:]
    target = "good_keywords" if stats["saved"] > 0 else "bad_keywords"
    mem[target] = list(dict.fromkeys(mem[target] + keywords_used))[-30:]
    if stats["publish_errors"]:
        mem["lessons"] = (mem["lessons"] + [f"{stats['at']}: 발행 실패 {stats['publish_errors']}건"])[-20:]
    _save_json(MEMORY_PATH, mem)


# ─────────────────────────── 설정 / 스케줄 / 메일 ───────────────────────────
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "memory" / "state.json"
INTERVALS = {"계속": 0, "10분 단위": 600, "1시간 단위": 3600, "하루 단위": 86400, "1주일 단위": 604800}
DEFAULT_CONFIG = {
    "interval": "1시간 단위",
    "max_items": 10,
    "domains": list(DOMAINS),
    "publish": True,
    "email_to": "hjh1014@naver.com",
    "email_per_day": 1,
}


def load_config() -> dict:
    return {**DEFAULT_CONFIG, **_load_json(CONFIG_PATH, {})}


def save_config(cfg: dict) -> None:
    _save_json(CONFIG_PATH, {**DEFAULT_CONFIG, **cfg})


def load_state() -> dict:
    return _load_json(STATE_PATH, {"last_run": None, "mail_date": None, "mail_count": 0})


def should_run(cfg: dict, state: dict) -> bool:
    """GitHub cron은 10분마다 깨어나고, 실제 실행 여부는 config.json의 주기로 판단."""
    if not state.get("last_run"):
        return True
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state["last_run"])).total_seconds()
    return elapsed >= INTERVALS.get(cfg["interval"], 3600) - 60  # cron 지연 여유 1분


def send_report_email(cfg: dict, state: dict, stats: dict) -> bool:
    """네이버 SMTP로 실행 리포트 발송. 하루 email_per_day 회 초과 시 생략.
    SMTP_USER / SMTP_PASSWORD 필요 (네이버 메일 → 환경설정 → POP3/IMAP 사용 설정,
    2단계 인증 사용 시 '애플리케이션 비밀번호' 발급)."""
    import smtplib
    from email.mime.text import MIMEText

    user, pw = os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASSWORD", "")
    if not (user and pw and cfg.get("email_to")) or cfg.get("email_per_day", 0) <= 0:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("mail_date") != today:
        state["mail_date"], state["mail_count"] = today, 0
    if state["mail_count"] >= cfg["email_per_day"]:
        return False
    body = "\n".join(f"{k}: {v}" for k, v in stats.items())
    msg = MIMEText(f"3dflowhub 실행 결과\n\n{body}", _charset="utf-8")
    msg["Subject"] = f"[3dflowhub] 저장 {stats['saved']} / 발행 {stats['published']}"
    msg["From"], msg["To"] = user, cfg["email_to"]
    try:
        with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.naver.com"), 465, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
        state["mail_count"] += 1
        return True
    except Exception as e:
        log.warning("메일 발송 실패: %s", e)
        return False


def run_from_config(force: bool = False) -> dict | None:
    cfg, state = load_config(), load_state()
    if not force and not should_run(cfg, state):
        log.info("주기(%s) 미도달 — 건너뜀", cfg["interval"])
        return None
    stats = run_pipeline(cfg["max_items"], cfg["domains"], cfg["publish"])
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    send_report_email(cfg, state, stats)
    _save_json(STATE_PATH, state)
    return stats


# ─────────────────────────── 대시보드용 조회 ───────────────────────────
def fetch_dashboard_rows(limit: int = 500) -> list[dict]:
    client = _notion()
    if client is None:
        return []
    rows, cursor = [], None
    try:
        while len(rows) < limit:
            res = _query_db(client, {"page_size": 100, **({"start_cursor": cursor} if cursor else {}),
                                     "sorts": [{"property": "CollectedAt", "direction": "descending"}]})
            for p in res["results"]:
                pr = p["properties"]
                rows.append({
                    "제목": "".join(t["plain_text"] for t in pr["Name"]["title"]),
                    "도메인": (pr.get("Domain", {}).get("select") or {}).get("name", ""),
                    "카테고리": (pr.get("Category", {}).get("select") or {}).get("name", ""),
                    "이미지": ((pr.get("Thumbnail", {}).get("files") or [{}])[0].get("external") or {}).get("url"),
                    "상태": (pr.get("Status", {}).get("select") or {}).get("name", ""),
                    "태그": ", ".join(t["name"] for t in pr.get("Tags", {}).get("multi_select", [])),
                    "수집일": (pr.get("CollectedAt", {}).get("date") or {}).get("start", ""),
                    "원문": pr.get("URL", {}).get("url"),
                    "티스토리": pr.get("TistoryURL", {}).get("url"),
                })
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
    except Exception as e:
        log.error("대시보드 조회 실패: %s", e)
    return rows


# ─────────────────────────── 엔트리포인트 ───────────────────────────
def run_pipeline(max_items: int = 10, domains: list[str] | None = None, publish: bool = True) -> dict:
    domains = [d for d in (domains or list(DOMAINS)) if d in DOMAINS]
    notion = _notion()
    ensure_notion_schema(notion)
    seen =notion_existing_urls(notion) if notion else set()
    seen |= set(_published().keys())

    items = collect(domains, max_items, seen)
    stats = {"at": datetime.now(timezone.utc).isoformat(), "collected": len(items),
             "saved": 0, "published": 0, "drafts": 0, "publish_errors": 0}

    for raw in items:
        try:
            item = summarize(raw)
            if not item:
                continue
            page_id = save_to_notion(notion, item)
            item["notion_id"] = page_id or ""  # 브라우저 발행 후 노션 상태 갱신용
            stats["saved"] += 1
            if publish:
                res = publish_to_tistory(item)
                if res["status"] == "published":
                    stats["published"] += 1
                    mark_notion_published(notion, page_id, res["url"])
                elif res["status"] == "draft_file":
                    stats["drafts"] += 1
                    stats["publish_errors"] += 1
        except Exception as e:  # 한 건의 실패가 전체를 죽이지 않도록
            log.exception("아이템 처리 실패 %s: %s", raw.get("url"), e)

    stats["errors"] = list(dict.fromkeys(RUN_ERRORS))[:5]
    reflect(stats, [raw["title"][:40] for raw in items[:5]])
    log.info("완료: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--max-items", type=int, default=int(os.getenv("MAX_ITEMS", 10)))
    p.add_argument("--domains", default=os.getenv("DOMAINS", ""), help="콤마 구분, 예: 'AI 3D,VFX'")
    p.add_argument("--no-publish", action="store_true")
    p.add_argument("--setup-notion", action="store_true", help="Notion DB 속성만 생성하고 종료")
    p.add_argument("--scheduled", action="store_true", help="config.json 주기 확인 후 실행")
    p.add_argument("--force", action="store_true", help="config.json 설정으로 주기 무시하고 즉시 실행")
    p.add_argument("--backfill", action="store_true", help="기존 노션 글에 카테고리/이미지 보강")
    a = p.parse_args()
    if a.backfill:
        print("보강 완료:", backfill_notion(_notion()), "건")
        raise SystemExit(0)
    if a.setup_notion:
        ensure_notion_schema(_notion())
        raise SystemExit(0)
    if a.scheduled or a.force:  # config.json 기준 실행 (GitHub Actions)
        run_from_config(force=a.force)
        raise SystemExit(0)
    run_pipeline(a.max_items, [d.strip() for d in a.domains.split(",") if d.strip()] or None, not a.no_publish)
