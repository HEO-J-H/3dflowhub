"""
3dflowhub core pipeline
=======================
[1] 동적 키워드 생성 → [2] 크롤링/수집 → [3] LLM 요약·분류 → GitHub(content/posts) 저장 (Notion 은 선택: notion_store.py)
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
from datetime import datetime, timedelta, timezone
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
DRAFT_DIR = ROOT / "drafts"  # 깃에 커밋됨 → CI 에서 만든 초안도 이 PC 발행기로 전달

# GitHub Models 는 2026-07-30 서비스 종료 → OpenAI 호환 무료 API 사용 (기본: Google Gemini 무료 티어)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENDPOINT = (os.getenv("LLM_BASE_URL") or
                "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/") + "/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL") or "gemini-flash-lite-latest"  # Actions 에서 빈 변수는 "" 로 전달됨

# 예비 LLM 공급자 (선택) — 키가 등록된 것만 사용. 주 공급자(Gemini) 한도 소진·장애 시 순서대로 넘어간다.
# 모델은 환경변수로 바꿀 수 있음 (무료 모델 목록은 각 공급자 대시보드 기준).
FALLBACK_PROVIDERS = [
    {"name": "groq", "key_env": "GROQ_API_KEY", "model_env": "GROQ_MODEL",
     "endpoint": "https://api.groq.com/openai/v1/chat/completions", "model": "openai/gpt-oss-120b"},
    {"name": "cerebras", "key_env": "CEREBRAS_API_KEY", "model_env": "CEREBRAS_MODEL",
     "endpoint": "https://api.cerebras.ai/v1/chat/completions", "model": "llama-3.3-70b"},
    {"name": "openrouter", "key_env": "OPENROUTER_API_KEY", "model_env": "OPENROUTER_MODEL",
     "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": "meta-llama/llama-3.3-70b-instruct:free"},
]
FALLBACK_DAILY = 300  # 공급자별 하루 상한 (config.json 의 llm_fallback_daily 로 변경)

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
        "seeds": ["3ds Max", "Autodesk 3ds Max", "Blender", "Maya", "V-Ray", "Corona Renderer", "ZBrush",
                  "Cinema 4D", "Substance 3D", "Houdini"],
        "feeds": ["https://www.cgchannel.com/feed/", "https://www.blendernation.com/feed/",
                  "https://www.blender.org/feed/", "https://code.blender.org/feed/",
                  # 3ds Max · MAXScript 커뮤니티 / 3ds Max 주력 렌더러(V-Ray·Corona) 공식 블로그
                  "https://www.reddit.com/r/3dsmax/.rss", "https://www.reddit.com/r/Maxscript/.rss",
                  "https://blog.chaos.com/rss.xml"],
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
SEED_CATEGORIES: dict[str, list[str]] = {  # 2단계: 도구·제품 (분류 축 하나로 통일)
    "3D DCC": ["Blender", "3ds Max", "Maya", "Cinema 4D", "ZBrush", "Houdini", "Substance 3D",
               "V-Ray·Corona", "Marvelous Designer", "기타 DCC"],
    "Game Engine": ["Unreal Engine", "Unity", "Godot", "UEFN·Fortnite", "게임 업계", "기타 엔진"],
    "VFX": ["After Effects", "Nuke", "Houdini FX", "DaVinci Resolve", "Unreal 가상 프로덕션", "스튜디오·작품"],
    "AI 3D": ["가우시안 스플래팅", "NeRF", "3D 생성 AI", "AI 텍스처·렌더링", "로보틱스·월드모델", "기타 AI 3D"],
}
# 3단계: 콘텐츠 유형 (고정) — 사이트에서 도구 게시판 안의 필터로 표시
TOPICS = ["업데이트·출시", "튜토리얼·팁", "플러그인·스크립트", "작품·제작 사례", "업계 소식", "연구·논문", "리뷰·비교"]
DEFAULT_TOPIC = "업계 소식"
# 도메인 표시 정보 (사이트 아이콘·주소, AI 분류용 설명)
DOMAIN_META: dict[str, dict] = {
    "3D DCC": {"icon": "🧊", "slug": "3d-dcc", "about": "3D modeling/rendering/animation software (Blender, Maya, 3ds Max…)"},
    "Game Engine": {"icon": "🎮", "slug": "game-engine", "about": "game engines and game development (Unreal, Unity, Godot)"},
    "VFX": {"icon": "💥", "slug": "vfx", "about": "visual effects, compositing, motion graphics, film/TV VFX"},
    "AI 3D": {"icon": "🤖", "slug": "ai-3d", "about": "AI for 3D: generative 3D, Gaussian splatting, NeRF, research"},
}
BUILTIN_DOMAINS = tuple(DOMAINS)
ARCHIVED_DOMAINS: list[str] = []  # 삭제(보관)된 사용자 분야 — 게시판만 유지


def apply_custom_domains(cfg: dict | None = None) -> list[str]:
    """config.json 의 custom_domains(대시보드에서 추가)를 DOMAINS 에 합침. 추가된 도메인 이름 목록 반환.
    형식: {"이름": {"seeds": [...], "feeds": [...], "icon": "📁", "about": "설명"}}"""
    if cfg is None:
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    added = []
    for name, spec in (cfg.get("custom_domains") or {}).items():
        name = str(name).strip()[:30]
        if not name or name in BUILTIN_DOMAINS or not isinstance(spec, dict):
            continue
        if spec.get("archived"):  # 삭제된 분야: 수집은 멈추고 사이트 게시판·주소는 유지
            DOMAIN_META[name] = {"icon": str(spec.get("icon") or "📁")[:4],
                                 "slug": "x-" + hashlib.blake2b(name.encode(), digest_size=4).hexdigest(),
                                 "about": str(spec.get("about") or name)[:200]}
            if name not in ARCHIVED_DOMAINS:
                ARCHIVED_DOMAINS.append(name)
            continue
        DOMAINS[name] = {"seeds": [s for s in spec.get("seeds", []) if isinstance(s, str)][:8] or [name],
                         "feeds": [f for f in spec.get("feeds", []) if isinstance(f, str) and f.startswith("http")][:8]}
        DOMAIN_META[name] = {"icon": str(spec.get("icon") or "📁")[:4],
                             "slug": "x-" + hashlib.blake2b(name.encode(), digest_size=4).hexdigest(),
                             "about": str(spec.get("about") or name)[:200]}
        SEED_CATEGORIES.setdefault(name, [])
        added.append(name)
    return added


def domain_topics() -> str:
    """AI 프롬프트용 도메인 설명 목록."""
    return "; ".join(f'"{d}" = {DOMAIN_META.get(d, {}).get("about", d)}' for d in DOMAINS)


MAX_CATEGORIES_PER_DOMAIN = 40  # 세부 카테고리 상한 (정리는 evolve.refine_taxonomy 가 주기적으로 병합)
MIN_RELEVANCE = 6  # LLM 관련도(0~10) 이 값 미만이면 수집 제외 (양보다 질: 5→6)
MAX_AGE_DAYS = 30  # 이보다 오래된 기사는 수집하지 않음


LLM_USAGE_PATH = Path(__file__).parent / "memory" / "llm_usage.json"  # 일별 LLM 호출 수
CONFIG_PATH = Path(__file__).parent / "config.json"
STRATEGY_PATH = Path(__file__).parent / "memory" / "strategy.json"  # [5] 자동 업데이트되는 수집·요약 전략
LAST_KEYWORDS: dict[str, list[str]] = {}  # 이번 실행에 사용한 검색 키워드
FEED_STATS: dict[str, int] = {}  # 이번 실행의 피드별 항목 수 (피드 건강도)


def strategy_version(notes: list[str]) -> str:
    """편집 가이드 묶음의 짧은 식별자 — 어떤 가이드로 실행했는지 기록해 성과와 연결."""
    return hashlib.blake2b("\n".join(notes).encode(), digest_size=4).hexdigest() if notes else "none"


def load_strategy() -> dict:
    return _load_json(STRATEGY_PATH, {"prompt_notes": [], "keyword_hints": {}, "extra_feeds": {},
                                      "blocked_feeds": [], "history": []})


# ─────────────────────────── 유틸 / 메모리 ───────────────────────────
def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


apply_custom_domains()  # 대시보드에서 추가한 수집 분야 반영


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().rstrip("/").encode()).hexdigest()[:16]


ISO_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def merge_json(base, other):
    """원격본(base)과 로컬본(other) 병합. 원칙: 원격이 기준, 로컬에서 '새로 생긴 것'만 더한다.
    - dict: 재귀 (원격에 없는 키는 로컬 값 추가)
    - list: 원격 목록 + 로컬에서 '원격과 공통인 마지막 항목' 뒤에 새로 붙은 항목만
            (원격에서 잘라내거나 지운 항목이 되살아나지 않음)
    - 숫자: 큰 값 (사용 횟수 등) / ISO 시각 문자열: 더 최근 값 / 그 외: 원격 우선"""
    if isinstance(base, dict) and isinstance(other, dict):
        out = dict(base)
        for k, v in other.items():
            out[k] = merge_json(out[k], v) if k in out else v
        return out
    if isinstance(base, list) and isinstance(other, list):
        key = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)  # noqa: E731
        remote = {key(x) for x in base}
        last_common = max((i for i, x in enumerate(other) if key(x) in remote), default=-1)
        tail = [x for x in other[last_common + 1:] if key(x) not in remote]
        if last_common == -1 and base:  # 공통 항목이 없으면 판단 불가 → 원격 유지
            tail = []
        out = list(base) + tail
        if out and all(isinstance(x, dict) and isinstance(x.get("at"), str) for x in out):
            out.sort(key=lambda x: x["at"])  # 실행 기록 등은 시간순 유지 (마지막 = 최신)
        return out
    if isinstance(base, bool) or isinstance(other, bool):
        return base
    if isinstance(base, (int, float)) and isinstance(other, (int, float)):
        return max(base, other)
    if isinstance(base, str) and isinstance(other, str) and ISO_TS_RE.match(base) and ISO_TS_RE.match(other):
        return max(base, other)
    return base if base not in (None, "") else other


# ─────────────────────────── AI 전 1차 거르기 ───────────────────────────
# 캐스케이드 원칙: 싸고 결정적인 규칙을 먼저, LLM 은 통과한 것만. 규칙은 '느슨하게'(재현율 우선) —
# 3D 관련 어휘가 하나도 없는 글만 버린다. 저장된 글로 재현율을 측정해 둔다(tests).
GENERIC_3D_TERMS = [
    "3d", "cgi", "vfx", "render", "shader", "texture", "modeling", "modelling", "sculpt", "rigging", "animation",
    "animator", "mesh", "polygon", "voxel", "point cloud", "photogrammetry", "motion capture", "mocap",
    "game engine", "game dev", "gamedev", "indie game", "level design", "procedural", "simulation", "particle",
    "compositing", "motion graphics", "visual effects", "virtual production", "ray tracing", "path tracing",
    "gpu", "rtx", "plugin", "add-on", "addon", "script", "splat", "nerf", "radiance field", "digital human",
    "avatar", "metaverse", "xr", "unreal", "unity", "blender", "houdini", "maya", "zbrush", "substance",
    "keyframe", "uv", "pbr", "hdri", "lighting", "cinematic", "previs", "world model", "robotics", "diffusion",
    "game", "games", "gaming", "engine", "steam", "console", "material", "viewport", "fbx", "gltf", "usd", "obj",
    "3dsmax", "workstation", "photorealistic", "digital twin", "bim", "drone", "motion-capture", "studio", "film", "trailer", "creative", "artist", "artcraft",
    "maxon", "chaos", "autodesk", "epic games", "sidefx", "foundry", "reallusion", "meshy", "tripo", "omniverse",
    "adobe", "nvidia", "80 level", "cg channel", "digital production", "befores & afters", "fxguide",
    "렌더", "모델링", "애니메이션", "텍스처", "셰이더", "게임", "그래픽", "시뮬레이션", "플러그인", "스크립트",
]


def relevance_vocab() -> list[str]:
    """도메인 시드·도구 카테고리·용어집·일반 3D 어휘 (소문자)."""
    words = set(GENERIC_3D_TERMS) | {k.lower() for k in GLOSSARY}
    for d, spec in DOMAINS.items():
        words |= {w.lower() for w in spec.get("seeds", [])}
    for cats in list(SEED_CATEGORIES.values()) + list(load_categories().values()):
        for c in cats:
            words |= {part.strip().lower() for part in re.split(r"[·/]", c) if len(part.strip()) >= 3
                      and not part.strip().startswith("기타")}
    return sorted(words, key=len, reverse=True)


def prefilter_score(text: str, vocab: list[str]) -> int:
    t = f" {text.lower()} "
    return sum(1 for w in vocab if (re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t)
                                    if len(w) <= 4 and w.isascii() else w in t))


def prefilter(candidates: list[dict]) -> list[dict]:
    """3D 관련 어휘가 제목·요약·URL 어디에도 없으면 AI 요약 전에 제외.
    전문 피드(cgchannel·80.lv·reddit r/3dsmax 등)는 이미 주제가 맞으므로 통과 — 범용 검색(구글 뉴스)만 거름."""
    vocab = relevance_vocab()
    kept = []
    for c in candidates:
        if "news.google.com" not in c.get("source", "") or prefilter_score(f"{c.get('title', '')} {c.get('rss_summary', '')} {c.get('url', '')}", vocab):
            kept.append(c)
        else:
            RUN_ERRORS.append("prefiltered")
    if len(kept) < len(candidates):
        log.info("1차 거르기: %d → %d건", len(candidates), len(kept))
    return kept


# ─────────────────────────── 에디터 큐레이션 (추천/숨김) ───────────────────────────
CURATION_PATH = ROOT / "memory" / "curation.json"  # [{"at", "id", "v": "pick"|"hide"|""}] 이벤트 로그 (병합 충돌 없음)
ROUNDUP_DIR = ROOT / "content" / "roundups"  # 도구별 정리 (evolve 가 주 1회 생성)


def curation_state() -> dict[str, str]:
    """글 id → 'pick' / 'hide' (마지막 이벤트 기준, 해제는 '')."""
    state: dict[str, str] = {}
    for ev in sorted(_load_json(CURATION_PATH, []), key=lambda x: x.get("at", "")):
        if isinstance(ev, dict) and ev.get("id"):
            state[ev["id"]] = ev.get("v", "")
    return {k: v for k, v in state.items() if v}


def set_curation(changes: dict[str, str], reasons: dict[str, str] | None = None) -> None:
    """{id: 'pick'|'hide'|'ok'|''} 변경분만 이벤트로 추가. reasons = 숨김(신고) 사유 → AI 관리자·전략이 학습.
    id 가 'learn:<가이드id>' 이면 기초 가이드 검토(ok=검토 완료, hide=사이트에서 숨김)."""
    cur = curation_state()
    log_ = _load_json(CURATION_PATH, [])
    now = datetime.now(timezone.utc).isoformat()
    log_ += [{"at": now, "id": i, "v": v, **({"reason": reasons[i][:200]} if reasons and reasons.get(i) else {})}
             for i, v in changes.items() if cur.get(i, "") != v]
    _save_json(CURATION_PATH, log_[-5000:])


TIPS_PATH = ROOT / "memory" / "tips.json"  # 운영자 실무 팁 [{"at","id": "learn:<가이드id>"|"p:<글id>","text"}]


def set_tip(target: str, text: str) -> None:
    """사람(운영자)의 실무 팁 — AI 가 흉내 낼 수 없는 경험. 빈 문자열이면 삭제."""
    log_ = _load_json(TIPS_PATH, [])
    log_.append({"at": datetime.now(timezone.utc).isoformat(), "id": target, "text": text.strip()[:1500]})
    _save_json(TIPS_PATH, log_[-3000:])


def tips() -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in sorted(_load_json(TIPS_PATH, []), key=lambda x: x.get("at", "")):
        if isinstance(ev, dict) and ev.get("id"):
            out[ev["id"]] = ev.get("text", "")
    return {k: v for k, v in out.items() if v}


def curation_reasons() -> dict[str, str]:
    """글 id → 마지막 숨김 사유."""
    out: dict[str, str] = {}
    for ev in sorted(_load_json(CURATION_PATH, []), key=lambda x: x.get("at", "")):
        if isinstance(ev, dict) and ev.get("id") and ev.get("reason"):
            out[ev["id"]] = ev["reason"]
    return out


def prune_drafts(days: int = 14) -> int:
    """오래된 티스토리 초안 정리 (계속 쌓여 '발행 대기 278개' 처럼 의미 없어지는 것 방지)."""
    if not DRAFT_DIR.exists():
        return 0
    cutoff = time.time() - days * 86400
    old = [f for f in list(DRAFT_DIR.glob("*.html")) + list(DRAFT_DIR.glob("promo/*.png")) if f.stat().st_mtime < cutoff
           or (re.match(r"(\d{8})_", f.name) and datetime.strptime(f.name[:8], "%Y%m%d").timestamp() < cutoff)]
    for f in old:
        f.unlink(missing_ok=True)
    return len(old)


# 인터넷 현황판(Streamlit Community Cloud): 저장소가 /mount/src 에 복제돼 실행됨. 저장은 GH_PAT 로 GitHub 에 푸시.
CLOUD = bool(os.getenv("DASHBOARD_CLOUD")) or Path("/mount/src").exists()
GH_REPO = os.getenv("GH_REPO", "HEO-J-H/3dflowhub")


def _push_remote() -> str:
    """푸시 대상: 클라우드처럼 자격 증명이 없는 곳은 GH_PAT 로 인증한 주소, 이 PC 는 origin(기존 로그인)."""
    tok = os.getenv("GH_PAT", "").strip()
    return f"https://x-access-token:{tok}@github.com/{GH_REPO}.git" if (CLOUD and tok) else "origin"


def _hide_token(text: str) -> str:
    tok = os.getenv("GH_PAT", "").strip()
    return text.replace(tok, "***") if tok else text


SNAPSHOT_FILES = ("memory/plan.json", "health.json")  # 매번 새로 계산 → 최신본 하나만 (점검 결과가 옛 문제와 섞이지 않게)  # 매 실행 새로 계산되는 스냅샷: 합치지 않고 더 최신('at') 것 사용


def merge_memory(path: str, remote, local):
    """memory JSON 병합. 스냅샷 파일은 숫자 '큰 값' 병합이 서로 다른 계산을 섞으므로 최신본 하나를 고른다."""
    if any(path.replace("\\", "/").endswith(x) for x in SNAPSHOT_FILES):
        if isinstance(remote, dict) and isinstance(local, dict):
            return local if local.get("at", "") >= remote.get("at", "") else remote
        return local if local is not None else remote
    merged = merge_json(remote, local)
    if path.replace("\\", "/").endswith("memory/strategy.json") and isinstance(merged, dict)             and isinstance(remote, dict) and isinstance(local, dict):
        # 편집 지침은 '교체'되는 값 — 목록 병합하면 옛 지침과 새 지침이 합쳐져 계속 늘어나므로 최신 쪽 하나를 쓴다
        newer = local if local.get("notes_updated_at", "") >= remote.get("notes_updated_at", "") else remote
        merged["prompt_notes"] = newer.get("prompt_notes", merged.get("prompt_notes", []))
        if newer.get("notes_updated_at"):
            merged["notes_updated_at"] = newer["notes_updated_at"]
    return merged


def git_sync(commit_paths: list[str] | None = None, message: str = "") -> str:
    """이 PC ↔ GitHub 동기화. memory/*.json 은 로컬본과 원격본을 내용 병합(충돌 없음).
    commit_paths 가 있으면 그 파일만 커밋·푸시 (예: 대시보드 설정 config.json). 실패 메시지 반환, 성공 시 ""."""
    import subprocess

    def git(*args: str):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    if CLOUD and not git("config", "user.email").stdout.strip():  # 클라우드 컨테이너엔 git 사용자 정보가 없음
        git("config", "user.name", "3dflowhub-dashboard")
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    # memory/*.json 은 GitHub 실행도 자주 바꾸므로 '먼저 커밋 후 pull' 하면 rebase 충돌 → pull·내용 병합 뒤에 커밋
    mem_commit = [p for p in commit_paths or [] if p.startswith("memory/")]
    pre_commit = [p for p in commit_paths or [] if p not in mem_commit]
    if pre_commit:
        git("add", *pre_commit)
        if git("diff", "--cached", "--quiet").returncode != 0:
            git("commit", "-q", "-m", message or "chore: update from local dashboard", "--", *pre_commit)
    tracked = [f for f in git("ls-files", "memory").stdout.split() if f.endswith(".json")]
    untracked = [f for f in git("ls-files", "-o", "--exclude-standard", "memory").stdout.split()
                 if f.endswith(".json")]  # CI 가 같은 파일을 커밋했으면 pull 이 막히므로 잠시 치움
    local = {f: _load_json(ROOT / f, None) for f in tracked + untracked}
    git("checkout", "--", *tracked)
    for f in untracked:
        (ROOT / f).unlink(missing_ok=True)
    # 로컬 실행이 만든 새 글·초안: 같은 이름이 원격에 생겼으면 pull 이 막히므로 잠시 치웠다가, 원격에 없는 것만 복원
    parked = {f: (ROOT / f).read_bytes() for f in
              git("ls-files", "-o", "--exclude-standard", "content", "drafts").stdout.split()}
    for f in parked:
        (ROOT / f).unlink(missing_ok=True)
    r = git("pull", "--rebase", "--autostash", "-q", "origin", "main")
    err = ""
    if r.returncode != 0:
        git("rebase", "--abort")
        err = "git pull 실패: " + (r.stderr or r.stdout)[:200]
    for f, data in parked.items():
        if not (ROOT / f).exists():
            (ROOT / f).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / f).write_bytes(data)
    for f, mine in local.items():
        if mine is not None:
            _save_json(ROOT / f, merge_memory(f, _load_json(ROOT / f, None), mine) if (ROOT / f).exists() else mine)
    if mem_commit and not err:  # 원격 최신본과 병합된 memory 를 이제 커밋
        # 먼저 밀려 있던 코드 커밋을 따로 푸시: '[skip ci]' 기록 커밋과 한 번에 올리면 GitHub 가 배포까지 건너뜀
        if git("rev-list", "--count", "origin/main..HEAD").stdout.strip() not in ("", "0") and "[skip ci]" in (message or ""):
            git("push", "-q", _push_remote(), "HEAD:main")
        git("add", *mem_commit)
        if git("diff", "--cached", "--quiet").returncode != 0:
            git("commit", "-q", "-m", message or "chore: update from local dashboard", "--", *mem_commit)
    ahead = git("rev-list", "--count", "origin/main..HEAD").stdout.strip() not in ("", "0")
    if (commit_paths or ahead) and not err:  # 미푸시 커밋이 남아 있어도 올림
        if CLOUD and _push_remote() == "origin":
            return "인터넷 현황판에서 저장하려면 Secrets 에 GH_PAT(저장소 쓰기 권한 토큰)가 필요합니다"
        p = git("push", "-q", _push_remote(), "HEAD:main")
        if p.returncode != 0:
            err = "git push 실패: " + _hide_token(p.stderr or p.stdout)[:200]
    return _hide_token(err)


def ci_commit(paths: list[str], message: str, tries: int = 4) -> bool:
    """GitHub Actions 전용 커밋·푸시. 다른 실행이 먼저 push 했으면 원격 최신본 위에 memory JSON 을 내용 병합해 재시도.
    (rebase -X theirs 는 동시에 들어온 원격 변경을 버리므로 사용하지 않음). content/ 변경이 푸시되면 True."""
    import subprocess
    import time as _t

    def git(*args: str):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    ours = {f: _load_json(ROOT / f, None) for f in git("ls-files", "-mo", "--exclude-standard", "memory").stdout.split()
            if f.endswith(".json")}
    # 이번 실행이 실제로 바꾼 파일만 커밋 (안 바꾼 파일을 add 하면 원격의 새 변경을 옛 내용으로 되돌림)
    touched = set(git("diff", "--name-only", "HEAD", "--", *paths).stdout.split()) | \
        set(git("ls-files", "-o", "--exclude-standard", "--", *paths).stdout.split())
    if not touched:
        return False
    paths = sorted(touched)
    for attempt in range(tries):
        git("fetch", "-q", "origin", "main")
        git("reset", "-q", "--mixed", "origin/main")  # 작업 파일(새 글·초안 포함)은 유지, 기준만 최신으로
        for f, mine in ours.items():
            if mine is None:
                continue
            remote = git("show", f"origin/main:{f}")
            base = json.loads(remote.stdout) if remote.returncode == 0 and remote.stdout.strip() else None
            _save_json(ROOT / f, merge_memory(f, base, mine) if base is not None else mine)
        git("add", *paths)
        if git("diff", "--cached", "--quiet").returncode == 0:
            return False
        content_changed = bool(git("diff", "--cached", "--name-only", "--", "content").stdout.strip())
        git("commit", "-q", "-m", message)
        if git("push", "-q", "origin", "HEAD:main").returncode == 0:
            return content_changed
        _t.sleep(5 * (attempt + 1))
    raise RuntimeError("push 재시도 실패")


def load_memory() -> dict:
    return _load_json(MEMORY_PATH, {"runs": [], "good_keywords": [], "bad_keywords": [], "lessons": []})


# ─────────────────────────── LLM (OpenAI 호환) ───────────────────────────
class LLMBudgetExceeded(RuntimeError):
    pass


LLM_SOURCE = "ci" if os.getenv("GITHUB_ACTIONS") else "local"  # 같은 API 키를 쓰는 실행 위치별 집계


LLM_QUOTA_PATH = Path(__file__).parent / "memory" / "llm_quota.json"  # 실제 429 한도 소진 기록


def llm_day() -> str:
    """Gemini 무료 한도는 미국 태평양 자정(한국 16~17시)에 리셋 → 그 기준의 날짜."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


def llm_quota_status() -> dict:
    """{'exhausted': bool, 'at_count': 소진 시점 호출 수, 'learned_limit': 최근 관측된 실제 한도}"""
    q = _load_json(LLM_QUOTA_PATH, {})
    hits = [v for v in q.values() if isinstance(v, int) and v > 0]
    return {"exhausted": llm_day() in q, "at_count": q.get(llm_day()),
            "learned_limit": min(hits[-7:]) if hits else None}


def _mark_quota_exhausted() -> None:
    q = {d: n for d, n in _load_json(LLM_QUOTA_PATH, {}).items() if d >= llm_day()[:8] + "01"}
    q.setdefault(llm_day(), llm_usage_today())
    _save_json(LLM_QUOTA_PATH, q)


LLM_FALLBACK_PATH = Path(__file__).parent / "memory" / "llm_fallback.json"  # {day: {공급자: 호출수, "공급자!": 소진}}


FALLBACK_RESERVE = 100  # 예비 공급자 비상용 보존량 (자동 배분에 쓰지 않음)


def fallback_providers() -> list[dict]:
    """키가 등록된 예비 공급자 (오늘 소진·상한 도달한 것 제외)."""
    day = _load_json(LLM_FALLBACK_PATH, {}).get(llm_day(), {})
    cap = int(_load_json(CONFIG_PATH, {}).get("llm_fallback_daily", FALLBACK_DAILY))
    out = []
    for f in FALLBACK_PROVIDERS:
        key = os.getenv(f["key_env"], "")
        if key and not day.get(f["name"] + "!") and day.get(f["name"], 0) < cap:
            out.append({**f, "key": key, "model": os.getenv(f["model_env"]) or f["model"],
                        "left": cap - day.get(f["name"], 0)})
    return out


def _fallback_count(name: str, exhausted: bool = False) -> None:
    data = {d: v for d, v in _load_json(LLM_FALLBACK_PATH, {}).items() if d >= llm_day()[:8] + "01"}
    day = data.setdefault(llm_day(), {})
    if exhausted:
        day[name + "!"] = True
    else:
        day[name] = day.get(name, 0) + 1
    _save_json(LLM_FALLBACK_PATH, data)


def llm_fallback_usage() -> dict:
    return {k: v for k, v in _load_json(LLM_FALLBACK_PATH, {}).get(llm_day(), {}).items() if not k.endswith("!")}


def llm_capacity_left() -> int:
    """오늘 남은 전체 AI 호출 여력 = 주 공급자 잔여 + 예비 공급자 잔여 (자동 모드 배분용)."""
    primary = 0 if llm_quota_status()["exhausted"] else \
        int(_load_json(CONFIG_PATH, {}).get("llm_daily_budget", 500)) - llm_usage_today()
    # 예비 공급자는 일부(fallback_reserve, 기본 100회)를 비상용으로 남김 — 배분에서 빼고, 성찰·관리 등 필수 호출만 씀
    reserve = int(_load_json(CONFIG_PATH, {}).get("fallback_reserve", FALLBACK_RESERVE))
    return max(0, primary) + max(0, sum(f["left"] for f in fallback_providers()) - reserve)


def llm_budget_left() -> int:
    """주 공급자 잔여 + (주 공급자가 바닥이면) 예비 공급자 잔여."""
    primary = 0 if llm_quota_status()["exhausted"] else \
        int(_load_json(CONFIG_PATH, {}).get("llm_daily_budget", 500)) - llm_usage_today()
    return primary if primary > 0 else sum(f["left"] for f in fallback_providers())


def llm_reset_kst() -> str:
    """다음 한도 리셋(태평양 자정)을 한국 시각으로."""
    from zoneinfo import ZoneInfo
    la = datetime.now(ZoneInfo("America/Los_Angeles"))
    nxt = (la + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M")


def llm_usage_today() -> int:
    """오늘 전체 사용량 = GitHub 실행분 + 이 PC 실행분 (memory 병합 시 위치별로 최대값 → 합산이 정확)."""
    day = llm_day()
    v = _load_json(LLM_USAGE_PATH, {}).get(day, 0)
    return sum(v.values()) if isinstance(v, dict) else int(v)


def _consume_llm_budget() -> None:
    """무료 티어 일일 한도 보호: 하루 호출 수가 config 의 llm_daily_budget 을 넘으면 중단."""
    day = llm_day()
    budget = int(_load_json(CONFIG_PATH, {}).get("llm_daily_budget", 500))
    if llm_quota_status()["exhausted"]:
        raise LLMBudgetExceeded("Gemini 실제 일일 한도 소진 (429) — 태평양 자정(한국 16~17시)에 리셋")
    if llm_usage_today() >= budget:
        raise LLMBudgetExceeded(f"오늘 LLM 호출 한도({budget}회) 도달")
    usage = {d: n for d, n in _load_json(LLM_USAGE_PATH, {}).items() if d >= day[:8] + "01"}  # 이번 달만
    today = usage.get(day) if isinstance(usage.get(day), dict) else {}
    today[LLM_SOURCE] = today.get(LLM_SOURCE, 0) + 1
    usage[day] = today
    _save_json(LLM_USAGE_PATH, usage)


def llm(prompt: str, system: str = "You are a concise assistant.", max_tokens: int = 800,
        json_mode: bool = False, temperature: float = 0.4) -> str:
    """주 공급자(Gemini) → 한도 소진·장애 시 예비 공급자(Groq·Cerebras·OpenRouter, 키 등록 시) 순서로 시도."""
    errors: list[str] = []
    quota_hit = False
    if LLM_API_KEY:
        try:
            _consume_llm_budget()
            return _llm_call(LLM_ENDPOINT, LLM_API_KEY, LLM_MODEL, prompt, system, max_tokens, json_mode, primary=True,
                             temperature=temperature)
        except LLMBudgetExceeded as e:
            quota_hit = True
            errors.append(str(e))
        except RuntimeError as e:
            errors.append(f"gemini: {e}")
    for f in fallback_providers():
        try:
            _fallback_count(f["name"])
            out = _llm_call(f["endpoint"], f["key"], f["model"], prompt, system, max_tokens, json_mode,
                            temperature=temperature)
            log.info("예비 공급자 %s 사용", f["name"])
            return out
        except LLMBudgetExceeded as e:
            _fallback_count(f["name"], exhausted=True)
            errors.append(f"{f['name']}: {e}")
        except RuntimeError as e:
            errors.append(f"{f['name']}: {e}")
    if not LLM_API_KEY and not errors:
        raise RuntimeError("LLM_API_KEY 미설정")
    if quota_hit and all("한도" in e or "429" in e for e in errors):
        raise LLMBudgetExceeded(" | ".join(errors)[:600])
    raise RuntimeError(" | ".join(errors)[:1200])


def _llm_call(endpoint: str, key: str, model: str, prompt: str, system: str, max_tokens: int,
              json_mode: bool, primary: bool = False, temperature: float = 0.4) -> str:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    errors = []
    for use_json in ((True, False) if json_mode else (False,)):  # JSON 모드 미지원 시 일반 모드 재시도
        payload = {**body, **({"response_format": {"type": "json_object"}} if use_json else {})}
        try:
            for attempt in range(4):  # 429/5xx(무료 한도·일시 장애)는 지수 백오프 재시도
                r = requests.post(endpoint, json=payload, timeout=60, headers=headers)
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
                wait = float(r.headers.get("retry-after") or 0) or 5 * 2 ** attempt
                log.info("LLM %s — %.0f초 후 재시도", r.status_code, wait)
                time.sleep(min(wait, 60))
            if r.status_code == 429:  # 재시도 후에도 429 = 오늘 한도 소진
                if primary:
                    if "quota" not in r.text.lower():
                        raise RuntimeError(f"429 rate limit: {r.text[:150]!r}")
                    _mark_quota_exhausted()
                    raise LLMBudgetExceeded(f"Gemini 실제 일일 한도 소진 (429, 오늘 {llm_usage_today()}회째)")
                raise LLMBudgetExceeded(f"429 한도: {r.text[:150]!r}")
            data = r.json() if r.ok else None
            if data and data.get("choices"):
                return (data["choices"][0]["message"].get("content") or "").strip()
            errors.append(f"{r.status_code} json={use_json}: {r.text[:200]!r}")
        except (requests.RequestException, ValueError) as e:
            errors.append(f"json={use_json}: {type(e).__name__} {e}"[:200])
    raise RuntimeError(" | ".join(errors))


def _parse_json(text: str) -> dict:
    """LLM JSON 응답 파싱. 쉼표 누락·잘린 출력·코드펜스는 json_repair 로 복구."""
    m = re.search(r"\{.*\}", text, re.S)
    raw = m.group(0) if m else text
    try:
        return json.loads(raw) if m else {}
    except ValueError:
        try:
            from json_repair import repair_json
            out = repair_json(raw, return_objects=True)
            if isinstance(out, dict) and out:
                log.info("깨진 JSON 복구 성공")
                return out
        except ImportError:
            pass
        raise


# ─────────────────────────── [1] 동적 키워드 ───────────────────────────
KEYWORD_CACHE_PATH = ROOT / "memory" / "keyword_cache.json"
KEYWORD_TTL_H = 6  # 10분마다 실행되므로 키워드는 6시간 재사용 (LLM 한도를 요약에 집중)


def generate_keywords(domains: list[str], per_domain: int = 2) -> dict[str, list[str]]:
    """검색 키워드를 AI 없이 조합 — AI 한도는 요약과 'AI 관리자'(manager.py)에 집중.
    재료(이미 학습된 것): 독자 관심 도구(조회수·추천) → AI 관리자/전략 키워드 힌트 → Search Console 검색어 → 시드.
    실행마다 순환해 같은 검색만 반복하지 않는다. config.json 의 llm_keywords=true 면 예전처럼 AI 로 생성.
    생성된 키워드 리스트 내에 도메인 간 중복되는 키워드가 있으면 제거(재시도)합니다."""
    def _clean_and_dedup(res_dict: dict[str, list[str]]) -> dict[str, list[str]]:
        seen_global = set()
        cleaned = {}
        for d, kws in res_dict.items():
            unique_d = []
            for kw in kws:
                kw_str = str(kw).strip()
                kw_norm = kw_str.lower()
                if kw_norm and kw_norm not in seen_global:
                    seen_global.add(kw_norm)
                    unique_d.append(kw_str)
            cleaned[d] = unique_d
        return cleaned

    if _load_json(CONFIG_PATH, {}).get("llm_keywords"):
        cached_result = _generate_keywords_cached(domains, per_domain)
        return _clean_and_dedup(cached_result)

    strategy = load_strategy()
    interest, hints = strategy.get("tool_interest", {}), strategy.get("keyword_hints", {})
    gsc_q = _gsc_queries()
    mem = load_memory()
    rr = dict(mem.get("kw_rr", {}))
    used: set[str] = set()
    out: dict[str, list[str]] = {}
    for d in domains:
        vocab = [w.lower() for w in DOMAINS[d]["seeds"] + list(interest.get(d, []))]
        pool = list(interest.get(d, [])) + list(hints.get(d, [])) \
            + [q for q in gsc_q if any(v in q.lower() for v in vocab)] + list(DOMAINS[d]["seeds"])
        pool = [k for k in dict.fromkeys(str(x).strip() for x in pool if str(x).strip())]
        start = rr.get(d, 0) % len(pool) if pool else 0
        picked = []
        for k in pool[start:] + pool[:start]:
            if k.lower() not in used:
                used.add(k.lower())
                picked.append(k)
            if len(picked) >= per_domain:
                break
        out[d] = list(dict.fromkeys(picked))
        rr[d] = start + per_domain

    # 같은 키워드가 도메인 간 중복되면 제거 (재시도 및 전역 고유화)
    seen_global: set[str] = set()
    for d in domains:
        unique_d = []
        for k in out.get(d, []):
            lk = k.lower()
            if lk not in seen_global:
                seen_global.add(lk)
                unique_d.append(k)
        out[d] = unique_d

    mem["kw_rr"] = rr
    _save_json(MEMORY_PATH, mem)
    return _clean_and_dedup(out)


def _generate_keywords_cached(domains: list[str], per_domain: int = 2) -> dict[str, list[str]]:
    """(선택) AI 키워드: 6시간 캐시, 한도 70% 이상 쓴 날은 시드."""
    cache = _load_json(KEYWORD_CACHE_PATH, {})
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cache.get("at", ""))).total_seconds() / 3600
    except ValueError:
        age_h = 1e9
    if age_h < KEYWORD_TTL_H and set(domains) <= set(cache.get("kws", {})):
        return {d: cache["kws"][d] for d in domains}
    budget = int(_load_json(CONFIG_PATH, {}).get("llm_daily_budget", 500))
    if llm_usage_today() >= budget * 0.7 or llm_quota_status()["exhausted"]:
        return {d: DOMAINS[d]["seeds"][:per_domain] for d in domains}
    out = _generate_keywords_llm(domains, per_domain)
    _save_json(KEYWORD_CACHE_PATH, {"at": datetime.now(timezone.utc).isoformat(), "kws": out})
    return out


def _gsc_queries() -> list[str]:
    try:
        import gsc
        return gsc.top_queries(10)
    except Exception:
        return []


def _generate_keywords_llm(domains: list[str], per_domain: int = 2) -> dict[str, list[str]]:
    """memory.json 의 성공/실패 키워드를 컨텍스트로 주입해 키워드를 조합."""
    mem = load_memory()
    hints = load_strategy().get("keyword_hints", {})
    result: dict[str, list[str]] = {}
    seen_keywords: set[str] = set()
    for d in domains:
        seeds = DOMAINS[d]["seeds"]
        prompt = (
            f"Domain: {d}\nSeed terms: {', '.join(seeds)}\n"
            f"Strategy hints (from self-reflection): {', '.join(hints.get(d, [])) or 'none'}\n"
            f"Google searches already bringing visitors (reuse wording if relevant): "
            f"{', '.join(_gsc_queries()) or 'none yet'}\n"
            f"Tools readers view most (prefer queries about these): "
            f"{', '.join(load_strategy().get('tool_interest', {}).get(d, [])) or 'none yet'}\n"
            f"Keywords that worked before: {', '.join(mem['good_keywords'][-10:]) or 'none'}\n"
            f"Keywords that failed: {', '.join(mem['bad_keywords'][-10:]) or 'none'}\n"
            f"Today: {datetime.now():%Y-%m-%d}\n"
            f"Return JSON {{\"keywords\": [...]}} with {per_domain} SHORT English news search queries "
            f"(2-4 words each, no years, no 'tutorial/updates' filler — e.g. 'Houdini 21', 'Gaussian splatting') "
            f"for the latest news in this domain."
        )
        try:
            kws = _parse_json(llm(prompt, max_tokens=150, json_mode=True)).get("keywords", [])
        except Exception as e:  # LLM 실패 시 시드로 폴백
            log.warning("키워드 생성 실패(%s) → 시드 사용: %s", d, e)
            kws = []
        domain_kws = []
        for k in kws:
            if isinstance(k, str):
                cleaned_k = k.strip()
                normalized_k = cleaned_k.lower()
                if normalized_k and normalized_k not in seen_keywords:
                    seen_keywords.add(normalized_k)
                    domain_kws.append(cleaned_k)
        if not domain_kws:
            for s in seeds:
                cleaned_s = s.strip()
                normalized_s = cleaned_s.lower()
                if normalized_s not in seen_keywords:
                    seen_keywords.add(normalized_s)
                    domain_kws.append(cleaned_s)
                if len(domain_kws) >= per_domain:
                    break
        result[d] = domain_kws[:per_domain]
    LAST_KEYWORDS.clear()
    LAST_KEYWORDS.update(result)
    return result


# ─────────────────────────── [2] 수집 ───────────────────────────
def _google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}+when:7d&hl=en-US&gl=US&ceid=US:en"


VIDEO_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})|player\.vimeo\.com/video/(\d+)")


GENERIC_IMAGE_RE = re.compile(r"arxiv[^/]*logo|arxiv\.org/static|news\.google|gstatic\.com|lh3\.googleusercontent\.com/J6_coFbog"
                              r"|/logo[^/]*\.(png|svg|jpg)|default[-_]?(og|share|thumb)|placeholder", re.I)


def is_generic_image(url: str) -> bool:
    return bool(url) and bool(GENERIC_IMAGE_RE.search(url))


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
    if is_generic_image(image):  # 사이트 로고·기본 썸네일은 대표 이미지로 쓰지 않음
        image = ""
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


def fetch_feed(url: str, timeout: int = 15):
    """타임아웃 있는 피드 파싱 (feedparser 단독 호출은 무한 대기 가능).
    같은 사이트 연속 요청은 2초 간격(Reddit 등 429 방지), HTTP 오류는 예외로 올려 '빈 피드'로 오인하지 않게 한다."""
    host = urlparse(url).netloc
    wait = 2.0 - (time.time() - _LAST_HIT.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _LAST_HIT[host] = time.time()
    r = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    r.raise_for_status()  # 403/429/5xx → 호출 측에서 '실패'로 처리 (피드 차단 카운트에 포함 안 됨)
    return feedparser.parse(r.content)


_LAST_HIT: dict[str, float] = {}


def normalize_feed_url(url: str) -> str:
    """피드 중복 비교용 (호스트 소문자, www 제거, 끝 / 제거, 'en-us' 같은 로케일 경로 제거)."""
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = re.sub(r"^/[a-z]{2}-[a-z]{2}(?=/)", "", p.path.lower()).rstrip("/")
    return f"{host}{path}" + (f"?{p.query}" if p.query else "")


SIMHASH_DISTANCE = 4  # 해밍 거리 ≤4 → 같은 기사로 간주


def title_simhash(title: str, bits: int = 64) -> int:
    """제목 근접 중복 판별용 64bit SimHash (단어 bigram, 고정 해시라 실행 간 일관)."""
    t = re.sub(r"\s[-–|:]\s[^-–|:]{2,30}$", "", title.lower())  # 끝의 ' - 매체명' 제거
    words = re.findall(r"\w+", t)
    shingles = [" ".join(p) for p in zip(words, words[1:])] or words
    v = [0] * bits
    for s in shingles:
        h = int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def is_near_duplicate(h: int, known: list[int]) -> bool:
    return any(bin(h ^ k).count("1") <= SIMHASH_DISTANCE for k in known)


def interleave_by_source(candidates: list[dict]) -> list[dict]:
    """도메인별로 출처(사이트)를 돌아가며 한 건씩 배치 — 예: blender 사이트 3곳이 앞자리를 모두 차지하는 문제 해결."""
    from collections import OrderedDict
    out = []
    for d in dict.fromkeys(c["hint_domain"] for c in candidates):
        groups: "OrderedDict[str, list]" = OrderedDict()
        for c in (c for c in candidates if c["hint_domain"] == d):
            groups.setdefault(c.get("source", ""), []).append(c)
        while any(groups.values()):
            for g in groups.values():
                if g:
                    out.append(g.pop(0))
    return out


def pick_by_weights(candidates: list[dict], domains: list[str], max_items: int,
                    weights: dict[str, float]) -> list[dict]:
    """조회수로 학습된 도메인 비중(evolve)대로 배분, 남는 자리는 라운드로빈으로 채움."""
    by_dom = {d: [c for c in candidates if c["hint_domain"] == d] for d in domains}
    total_w = sum(weights.get(d, 1.0) for d in domains) or 1
    quota = {d: int(max_items * weights.get(d, 1.0) / total_w) for d in domains}
    picked = []
    for d in sorted(domains, key=lambda x: -weights.get(x, 1.0)):
        take = by_dom[d][:quota[d]]
        picked += take
        by_dom[d] = by_dom[d][len(take):]
    while len(picked) < max_items and any(by_dom.values()):
        for d in sorted(domains, key=lambda x: -weights.get(x, 1.0)):
            if by_dom[d] and len(picked) < max_items:
                picked.append(by_dom[d].pop(0))
    return picked


def collect(domains: list[str], max_items: int, seen: set[str]) -> list[dict]:
    keywords = generate_keywords(domains)
    candidates: list[dict] = []
    known_hashes: list[int] = list(load_memory().get("title_hashes", []))
    seed_rr: dict[str, int] = dict(load_memory().get("seed_rr", {}))  # 분야별 시드 순환 위치
    for d in domains:
        strategy = load_strategy()
        blocked = {normalize_feed_url(u) for u in strategy.get("blocked_feeds", [])}
        feeds = {}
        for f in DOMAINS[d]["feeds"] + strategy.get("extra_feeds", {}).get(d, []):
            feeds.setdefault(normalize_feed_url(f), f)  # 같은 피드의 다른 표기 중복 제거
        # 시드 순환: 실행마다 분야의 시드 도구 하나를 정확히 검색 → 특정 도구(예: Blender)만 쏠리는 것 방지
        seeds = DOMAINS[d].get("seeds") or []
        rr = seed_rr.get(d, 0)
        rotated = [f'"{seeds[rr % len(seeds)]}"'] if seeds else []
        seed_rr[d] = rr + 1
        sources = [f for n, f in feeds.items() if n not in blocked] + \
            [_google_news_rss(k) for k in dict.fromkeys(rotated + keywords[d])]
        for src in sources:
            try:
                feed = fetch_feed(src)
            except Exception as e:
                log.warning("피드 실패 %s: %s", src, e)
                continue
            if "news.google.com" not in src:
                FEED_STATS[src] = len(feed.entries)
            if not feed.entries and "news.google.com" not in src:  # 구글 뉴스 검색 0건은 정상(키워드 탓) → 오류 아님
                RUN_ERRORS.append(f"empty feed: {src}")
            for e in feed.entries[:10]:
                link = e.get("link", "")
                if not link or url_hash(link) in seen:
                    continue
                title = e.get("title", "").strip()
                if not title or any(kw in title.lower() for kw in ["하드웨어", "스마트폰", "hardware", "smartphone", "phone"]):
                    RUN_ERRORS.append("prefiltered")
                    continue
                published = e.get("published_parsed") or e.get("updated_parsed")
                if published and (time.time() - calendar.timegm(published)) > MAX_AGE_DAYS * 86400:
                    continue  # 오래된 기사 제외
                seen.add(url_hash(link))
                sh = title_simhash(title)
                if is_near_duplicate(sh, known_hashes):  # 다른 매체의 같은 기사
                    continue
                known_hashes.append(sh)
                candidates.append({
                    "source": src,  # 피드 단위로 교차 (같은 사이트의 다른 피드도 구분)
                    "simhash": sh,
                    "title": title,
                    "url": link,
                    "hint_domain": d,
                    "rss_summary": BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ")[:800],
                })
    candidates = prefilter(candidates)  # AI 요약 전 규칙 기반 1차 거르기 (한도 절약)
    candidates = interleave_by_source(candidates)  # 한 출처가 상위를 독점하지 않도록 출처별 교차
    mem_rr = load_memory()
    mem_rr["seed_rr"] = seed_rr
    _save_json(MEMORY_PATH, mem_rr)
    picked = pick_by_weights(candidates, domains, max_items, load_strategy().get("domain_weights") or {})
    mem = load_memory()  # 선택된 기사 지문 저장 → 이후 실행에서도 같은 기사 재수집 방지
    mem["title_hashes"] = (mem.get("title_hashes", []) + [c["simhash"] for c in picked])[-800:]
    _save_json(MEMORY_PATH, mem)
    log.info("수집 후보 %d건 → 선택 %d건", len(candidates), len(picked))
    return picked


# ─────────────────────────── [3] LLM 요약·분류 ───────────────────────────
SUMMARY_SYSTEM = (
    "You are an editor for a Korean creative-tech curation blog (3D, game engines, VFX, AI 3D and related fields). "
    "Write in natural Korean. Never invent facts not in the source. "
    "Keep names of software, plugins, scripting languages, APIs, file formats and product features in their OFFICIAL "
    "English spelling — never transliterate them into Hangul (write MAXScript, MacroScript, 3ds Max, Blender, "
    "Unreal Engine, Unity, Houdini, ZBrush, V-Ray, Geometry Nodes, Python, USD, FBX). Translate ordinary words only."
)


KNOWLEDGE_DIR = ROOT / "knowledge"  # 역할별 업무 교본 (사람이 고쳐 쓸 수 있는 마크다운)


def playbook(*names: str, limit: int = 6000) -> str:
    """에이전트가 일하기 전에 읽는 교본. knowledge/<이름>.md 를 이어 붙여 system 프롬프트에 넣는다.
    없는 교본은 건너뜀. 토큰을 아끼려고 주석 줄은 빼고 길이 제한."""
    parts = []
    for n in names:
        f = KNOWLEDGE_DIR / f"{n}.md"
        if f.exists():
            parts.append(f.read_text(encoding="utf-8").strip())
    text = "\n\n".join(parts)
    return ("\n\n=== PLAYBOOK (read before working; follow it) ===\n" + text[:limit]) if text else ""


RUN_ERRORS: list[str] = []  # 이번 실행의 실패 사유 (memory.json 에 기록)


def load_categories() -> dict[str, list[str]]:
    mem = load_memory()
    saved, merged = mem.get("categories", {}), mem.get("category_merges", {})
    return {d: [c for c in dict.fromkeys(SEED_CATEGORIES.get(d, []) + saved.get(d, []))
                if f"{d}/{c}" not in merged] for d in DOMAINS}


def _count_category(domain: str, category: str) -> None:
    mem = load_memory()
    counts = mem.setdefault("category_counts", {})
    counts[f"{domain}/{category}"] = counts.get(f"{domain}/{category}", 0) + 1
    _save_json(MEMORY_PATH, mem)


def clean_tool_name(domain: str, name: str) -> str:
    """도구 이름 정리: 금지 문자 치환·길이 제한, 콘텐츠 유형 이름 거부, 병합된 이름은 최종 대상으로 (체인 추적)."""
    name = re.sub(r"[/|<>,]", "·", (name or "").strip())[:24]
    if not name or name in TOPICS:
        return ""
    merges = load_memory().get("category_merges", {})
    for _ in range(10):
        nxt = merges.get(f"{domain}/{name}")
        if not nxt or nxt == name:
            break
        name = nxt
    return name


def register_new_option(domain: str, category: str) -> str:
    """사용 횟수 없이 카테고리 선택지만 추가 (taxonomy split 용). 추가된 이름, 이미 있거나 실패 시 ""."""
    category = clean_tool_name(domain, category)
    cats = load_categories().get(domain, [])
    if len(category) > 24:  # 잘린 이름 방지: 길면 추가하지 않음
        return ""
    if not category or category in cats or len(cats) >= MAX_CATEGORIES_PER_DOMAIN:
        return ""
    mem = load_memory()
    mem.setdefault("categories", {}).setdefault(domain, []).append(category)
    _save_json(MEMORY_PATH, mem)
    return category


def register_category(domain: str, category: str) -> str:
    """세부 카테고리 확정. 새 이름이면 memory.json 에 추가 (도메인당 최대 개수 초과 시 첫 카테고리로 대체)."""
    category = clean_tool_name(domain, category)
    cats = load_categories()[domain]
    fallback = next((c for c in cats if c.startswith("기타")), cats[0] if cats else "기타")  # 미분류는 '기타 …'
    if not category:
        return fallback
    if category in cats:
        _count_category(domain, category)
        return category
    if len(cats) >= MAX_CATEGORIES_PER_DOMAIN:
        return fallback
    mem = load_memory()
    mem.setdefault("categories", {}).setdefault(domain, []).append(category)
    _save_json(MEMORY_PATH, mem)
    _count_category(domain, category)
    log.info("새 카테고리 추가: %s / %s", domain, category)
    return category


# 용어집(음역·오번역 교정)은 terms.py
from terms import GLOSSARY, _GLOSS_RE, apply_glossary, fix_terms, glossary_extra, term_aliases  # noqa: E402,F401


def normalize_summary(data: dict, item: dict) -> dict:
    """LLM JSON 형태 보정 — 누락/형식 오류로 노션 저장이 실패하지 않도록."""
    data = data if isinstance(data, dict) else {}
    sections = []
    for s in data.get("sections") or []:
        if isinstance(s, dict) and (s.get("heading") or s.get("body")):
            sections.append({"heading": str(s.get("heading") or "").strip() or "내용",
                             "body": str(s.get("body") or "").strip()})
        elif isinstance(s, str) and s.strip():
            sections.append({"heading": "내용", "body": s.strip()})
    data["sections"] = sections
    for key in ("title_ko", "summary", "insight"):
        if not isinstance(data.get(key), str):
            data[key] = "" if key != "title_ko" else ""
    data["title_ko"] = data["title_ko"].strip() or item["title"]
    if data.get("domain") not in DOMAINS:
        data["domain"] = item["hint_domain"]
    cat = data.get("category")
    data["category"] = cat if isinstance(cat, str) else (cat[0] if isinstance(cat, list) and cat
                                                          and isinstance(cat[0], str) else "")
    data["faq"] = [f for f in data.get("faq") or [] if isinstance(f, dict)]
    data["topic"] = data.get("topic") if data.get("topic") in TOPICS else DEFAULT_TOPIC
    apply_glossary(data)
    return data


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
        ' "title_ko": search-friendly Korean title, 25-45 chars, main tool/product name + key search term first, '
        'no clickbait,\n'
        f' "domain": one of {json.dumps(list(DOMAINS), ensure_ascii=False)} ({domain_topics()}),\n'
        ' "category": the main TOOL / PRODUCT / TECHNOLOGY this article is about (exact name from the existing list '
        'of that domain, e.g. "Blender", "3ds Max", "Unreal Engine", "Unity", "Nuke", "가우시안 스플래팅"). Never put '
        'the content type here (no "업데이트", "튜토리얼", "사례"). If a clearly different tool/product not in the list, '
        'use its official name (<=20 chars); if no single tool, use the domain\'s "기타 …" entry,\n'
        f' "topic": exactly one of {json.dumps(TOPICS, ensure_ascii=False)} (the content type),\n'
        ' "tags": 3-6 short tags,\n'
        ' "summary": one-sentence Korean summary,\n'
        ' "insight": 3-5 sentences of ORIGINAL Korean commentary for Korean 3D/VFX/game artists — why it matters, '
        'how to apply it in practice, who should care. Do not restate the article,\n'
        ' "sections": list of 4-6 objects {"heading": str, "body": str} in Korean (each body 3-5 sentences, '
        'factual, from the source),\n'
        ' "faq": 2-3 objects {"q": str, "a": str} — questions Korean readers would search for, answered from the '
        'source in 1-3 sentences,\n'
        f' "relevance": 0-10 how directly this is about any of these fields: {domain_topics()} '
        '(weather, politics, general business, music news = 0-2; a different thing that merely shares a tool name '
        '— Harry Houdini the magician, Maya civilization, a kitchen blender, unity as a word, stock-only '
        'news — = 0)'
    )
    notes = load_strategy().get("prompt_notes", [])
    system = SUMMARY_SYSTEM + playbook("editor", limit=2500) + (
        "\nEditorial guidelines learned from past runs:\n- " + "\n- ".join(notes) if notes else "")
    try:
        data = _parse_json(llm(prompt, system=system, max_tokens=1400, json_mode=True))
    except LLMBudgetExceeded:
        raise
    except Exception as e:
        log.warning("요약 실패 %s: %s", item["url"], e)
        RUN_ERRORS.append(f"summarize: {str(e)[:600]}")
        return None
    try:
        relevance = float(data.get("relevance", 10)) if isinstance(data, dict) else 10.0
    except (TypeError, ValueError):
        relevance = 10.0
    if relevance < MIN_RELEVANCE:  # 주제와 무관한 기사(구글 뉴스 오검색 등) 제외
        log.info("관련도 %.0f — 제외: %s", relevance, item["title"][:60])
        RUN_ERRORS.append("off-topic")
        return None
    data = normalize_summary(data, item)
    if not data["sections"] and not data.get("summary"):
        # 일부 모델(Groq 등)은 무관한 기사에 relevance 대신 빈 응답을 줌 → 오류가 아니라 주제 밖으로 집계
        log.info("빈 요약(주제 밖으로 판단) — 제외: %s", item["title"][:60])
        RUN_ERRORS.append("off-topic")
        return None
    if not data["sections"]:
        log.warning("LLM 응답에 sections 없음: %s", item["url"])
        RUN_ERRORS.append(f"no sections: {str(data)[:200]}")
        return None
    data["category"] = register_category(data["domain"], data["category"])
    tags = data.get("tags")
    if isinstance(tags, str):
        data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        normalized = []
        for t in tags:
            if isinstance(t, str):
                normalized.extend([sub.strip() for sub in t.split(",") if sub.strip()])
        data["tags"] = normalized
    return {**item, **data, "media": media, "collected_at": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────── Notion ───────────────────────────
def notion_enabled() -> bool:
    """config.json 의 save_notion (대시보드에서 끄면 GitHub 만 사용)."""
    return bool(_load_json(CONFIG_PATH, {}).get("save_notion", True))


def _notion() -> "NotionClient | None":
    if not (NOTION_TOKEN and NotionClient and notion_enabled()):
        return None
    return NotionClient(auth=NOTION_TOKEN, notion_version="2022-06-28")  # properties 기반 API 고정


# 실제 Notion API 코드는 notion_store.py (비활성 시 불러오지 않음)
def ensure_notion_schema(client) -> None:
    if client is not None:
        import notion_store
        notion_store.ensure_notion_schema(client)


def _query_db(client, body: dict) -> dict:
    import notion_store
    return notion_store._query_db(client, body)


def notion_existing_urls(client) -> set[str]:
    if client is None:
        return set()
    import notion_store
    return notion_store.notion_existing_urls(client)


def save_to_notion(client, item: dict) -> str | None:
    if client is None:
        return None
    import notion_store
    return notion_store.save_to_notion(client, item)


def backfill_notion(client, limit: int = 100) -> int:
    if client is None:
        return 0
    import notion_store
    return notion_store.backfill_notion(client, limit)


POSTS_DIR = ROOT / "content" / "posts"  # GitHub Pages 원본 데이터 (build_site.py 가 HTML 로 변환)
POST_FIELDS = ("title_ko", "title", "url", "domain", "category", "topic", "tags", "summary", "insight",
               "sections", "faq", "media", "collected_at", "notion_id")


def save_post_json(item: dict) -> Path:
    """노션과 같은 내용을 content/posts/<날짜>-<해시>.json 으로 저장 (커밋되어 Pages 로 배포)."""
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    day = (item.get("collected_at") or datetime.now(timezone.utc).isoformat())[:10]
    path = POSTS_DIR / f"{day}-{url_hash(item['url'])}.json"
    data = {k: item.get(k) for k in POST_FIELDS}
    data["id"] = path.stem
    _save_json(path, data)
    return path


def related_posts(client, item: dict, limit: int = 3) -> list[dict]:
    """같은 세부 카테고리 → 같은 도메인 순으로 이미 발행된 글 (조회수 높은 순).
    노션 미사용 시: GitHub Pages 사이트의 같은 분류 글로 링크 (사이트 유입도 늘어남)."""
    if client is None:
        posts = [_load_json(f, {}) | {"_id": f.stem} for f in POSTS_DIR.glob("*.json")]
        posts = [p for p in posts if p.get("title_ko") and p.get("url") != item.get("url")]
        posts.sort(key=lambda p: p.get("collected_at") or "", reverse=True)
        same = [p for p in posts if p.get("domain") == item.get("domain")]
        ranked = [p for p in same if p.get("category") == item.get("category")] + same
        out, seen_ids = [], set()
        for p in ranked:
            if p["_id"] not in seen_ids:
                seen_ids.add(p["_id"])
                out.append({"url": f"{SITE_URL}p/{p['_id']}.html", "title": p["title_ko"]})
        return out[:limit]
    out: list[dict] = []
    filters = []
    if item.get("category"):
        filters.append({"property": "Category", "select": {"equals": item["category"]}})
    filters.append({"property": "Domain", "select": {"equals": item["domain"]}})
    for f in filters:
        try:
            res = _query_db(client, {"page_size": 10, "filter": {"and": [
                f, {"property": "TistoryURL", "url": {"is_not_empty": True}}]},
                "sorts": [{"property": "Views", "direction": "descending"}]})
        except Exception as e:
            log.debug("관련 글 조회 실패: %s", e)
            break
        for p in res.get("results", []):
            url = p["properties"]["TistoryURL"]["url"]
            if url not in [r["url"] for r in out]:
                out.append({"url": url, "title": "".join(t["plain_text"] for t in p["properties"]["Name"]["title"])})
        if len(out) >= limit:
            break
    return out[:limit]


def mark_notion_published(client, page_id: str | None, post_url: str) -> None:
    if client and page_id:
        import notion_store
        notion_store.mark_notion_published(client, page_id, post_url)


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
        ' "title_ko": search-friendly Korean title, 25-45 chars, main tool/product name + key search term first, '
        'no clickbait,\n'
        f' "domain": one of {json.dumps(list(DOMAINS), ensure_ascii=False)} ({domain_topics()}),\n'
        ' "category": the main TOOL / PRODUCT / TECHNOLOGY this article is about (exact name from the existing list '
        'of that domain, e.g. "Blender", "3ds Max", "Unreal Engine", "Unity", "Nuke", "가우시안 스플래팅"). Never put '
        'the content type here (no "업데이트", "튜토리얼", "사례"). If a clearly different tool/product not in the list, '
        'use its official name (<=20 chars); if no single tool, use the domain\'s "기타 …" entry,\n'
        f' "topic": exactly one of {json.dumps(TOPICS, ensure_ascii=False)} (the content type),\n'
        ' "tags": 3-6 short tags,\n'
        ' "summary": one-sentence Korean summary,\n'
        ' "insight": 3-5 sentences of ORIGINAL Korean commentary for Korean 3D/VFX/game artists — why it matters, '
        'how to apply it in practice, who should care. Do not restate the article,\n'
        ' "sections": list of 4-6 objects {"heading": str, "body": str} in Korean (each body 3-5 sentences, '
        'factual, from the source),\n'
        ' "faq": 2-3 objects {"q": str, "a": str} — questions Korean readers would search for, answered from the '
        'source in 1-3 sentences,\n'
        f' "relevance": 0-10 how directly this is about any of these fields: {domain_topics()} '
        '(weather, politics, general business, music news = 0-2; a different thing that merely shares a tool name '
        '— Harry Houdini the magician, Maya civilization, a kitchen blender, unity as a word, stock-only '
        'news — = 0)'
    )
    notes = load_strategy().get("prompt_notes", [])
    system = SUMMARY_SYSTEM + playbook("editor", limit=2500) + (
        "\nEditorial guidelines learned from past runs:\n- " + "\n- ".join(notes) if notes else "")
    try:
        data = _parse_json(llm(prompt, system=system, max_tokens=1400, json_mode=True))
    except LLMBudgetExceeded:
        raise
    except Exception as e:
        log.warning("요약 실패 %s: %s", item["url"], e)
        RUN_ERRORS.append(f"summarize: {str(e)[:600]}")
        return None
    try:
        relevance = float(data.get("relevance", 10)) if isinstance(data, dict) else 10.0
    except (TypeError, ValueError):
        relevance = 10.0
    if relevance < MIN_RELEVANCE:  # 주제와 무관한 기사(구글 뉴스 오검색 등) 제외
        log.info("관련도 %.0f — 제외: %s", relevance, item["title"][:60])
        RUN_ERRORS.append("off-topic")
        return None
    data = normalize_summary(data, item)
    if not data["sections"] and not data.get("summary"):
        # 일부 모델(Groq 등)은 무관한 기사에 relevance 대신 빈 응답을 줌 → 오류가 아니라 주제 밖으로 집계
        log.info("빈 요약(주제 밖으로 판단) — 제외: %s", item["title"][:60])
        RUN_ERRORS.append("off-topic")
        return None
    if not data["sections"]:
        log.warning("LLM 응답에 sections 없음: %s", item["url"])
        RUN_ERRORS.append(f"no sections: {str(data)[:200]}")
        return None
    
    # 요약된 본문 글자 수(태그 제외 본문 텍스트 기준) 검증 로직 추가
    full_text_sum = "".join(f"{s.get('heading', '')} {s.get('body', '')}" for s in data["sections"])
    if len(full_text_sum) < 1500:
        log.warning("요약된 본문 글자 수가 1,500자 미만입니다 (%d자): %s", len(full_text_sum), data.get("title_ko", ""))
        RUN_ERRORS.append("short post")

    data["category"] = register_category(data["domain"], data["category"])
    tags = data.get("tags")
    if isinstance(tags, str):
        data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    elif isinstance(tags, list):
        normalized = []
        for t in tags:
            if isinstance(t, str):
                normalized.extend([sub.strip() for sub in t.split(",") if sub.strip()])
        data["tags"] = normalized
    return {**item, **data, "media": media, "collected_at": datetime.now(timezone.utc).isoformat()}


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
    label = item["domain"] + (f" › {item['category']}" if item.get("category") else "") +         (f" › {item['topic']}" if item.get("topic") else "")
    intro = (hero + f'<p style="font-size:1.05em;"><b>한 줄 요약</b> — {html.escape(item.get("summary", ""))}</p>\n'
             f'<p style="color:#888;">분류: {html.escape(label)}</p>\n')
    if item.get("insight"):
        part_2 += (f'<h2>💡 에디터 코멘트</h2>\n<blockquote style="border-left:4px solid #4a90e2;padding:8px 14px;">'
                   f'{html.escape(item["insight"])}</blockquote>\n')
    faq = [f for f in item.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")]
    if faq:  # 검색 질의형 유입·스니펫 노출용
        part_2 += "<h2>❓ 자주 묻는 질문</h2>\n" + "".join(
            f'<p><b>Q. {html.escape(f["q"])}</b><br/>A. {html.escape(f["a"])}</p>\n' for f in faq[:3])
    related = [r for r in item.get("related") or [] if r.get("url") and r.get("title")]
    if related:  # 내부 링크 → 방문당 페이지뷰 증가
        part_2 += "<h2>📚 함께 보면 좋은 글</h2>\n<ul>" + "".join(
            f'<li><a href="{html.escape(r["url"])}">{html.escape(r["title"])}</a></li>' for r in related[:3]) + "</ul>\n"
    source = (f'<hr/><p>원문:<a href="{html.escape(item["url"])}" target="_blank" rel="noopener nofollow">'
              f'{html.escape(item["title"])}</a></p>\n'
              f'<p style="color:#999;font-size:0.85em;">본 글은 3dflowhub가 원문을 요약·번역한 큐레이션 콘텐츠입니다.</p>\n')

    ad = {p: (ad_banner_html(p) if p in AD_POSITIONS else "") for p in ("top", "middle", "bottom")}
    html_out = intro + ad["top"] + part_1 + ad["middle"] + part_2 + source + ad["bottom"]
    
    # 요약된 본문 글자 수(태그 제외) 검증 (1,500자 미만인 경우 short post 경고 로그 및 RUN_ERRORS 기록)
    text_only = BeautifulSoup(html_out, "html.parser").get_text(strip=True)
    if len(text_only) < 1500:
        log.warning("short post: 요약된 본문 글자 수가 1,500자 미만입니다 (%d자): %s", len(text_only), item.get("title_ko", item.get("title", "")))
        if "short post" not in RUN_ERRORS:
            RUN_ERRORS.append("short post")

    return html_out


# ─────────────────────────── [4] 티스토리 발행 ───────────────────────────
def _published() -> dict:
    return _load_json(PUBLISHED_LOG, {})


def _save_draft_file(item: dict, content: str) -> str:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{url_hash(item['url'])}.html"
    tags = list(dict.fromkeys(item.get("tags", []) + ([item["topic"]] if item.get("topic") else [])))
    header = (f"<!-- TITLE: {item['title_ko']} | TAGS: {','.join(tags)} "
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
    health = mem.setdefault("feed_health", {})  # 피드별 연속 0건 횟수 → evolve 가 차단 판단
    for url, n in FEED_STATS.items():
        health[url] = 0 if n else health.get(url, 0) + 1
    if stats["publish_errors"]:
        mem["lessons"] = (mem["lessons"] + [f"{stats['at']}: 발행 실패 {stats['publish_errors']}건"])[-20:]
    _save_json(MEMORY_PATH, mem)


# ─────────────────────────── 설정 / 스케줄 / 메일 ───────────────────────────
STATE_PATH = ROOT / "memory" / "state.json"
INTERVALS = {"계속": 0, "10분 단위": 600, "1시간 단위": 3600, "하루 단위": 86400, "1주일 단위": 604800}
DEFAULT_CONFIG = {
    "interval": "1시간 단위",
    "max_items": 10,
    "domains": list(DOMAINS),
    "publish": True,
    "email_to": "hjh1014@naver.com",
    "email_per_day": 1,
    "llm_daily_budget": 500,  # Gemini 무료 티어 보호 (AI Studio 에서 확인한 내 한도에 맞게 조정)
    "burst_items": 3,          # '계속'(10분마다) 모드에서 한 번에 처리할 글 수
}


def load_config() -> dict:
    return {**DEFAULT_CONFIG, **_load_json(CONFIG_PATH, {})}


def save_config(cfg: dict) -> None:
    """기존 설정 위에 덮어쓰기 (일부 키만 넘겨도 다른 설정—추가 분야·통계 코드 등—이 지워지지 않음)."""
    _save_json(CONFIG_PATH, {**DEFAULT_CONFIG, **_load_json(CONFIG_PATH, {}), **cfg})


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
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    _save_json(STATE_PATH, state)  # 실패해도 10분마다 재시도 폭주하지 않도록 먼저 기록
    n = cfg["max_items"] if INTERVALS.get(cfg["interval"], 3600) >= 3600 else min(cfg["max_items"], cfg["burst_items"])
    if cfg.get("auto_mode"):  # 자동 모드: AI 관리자가 오늘 남은 여력을 뉴스·가이드·정리에 배분
        try:
            import manager
            n = manager.plan_today()["news_per_run"]
        except Exception as e:
            log.warning("자동 배분 실패 — 기본 수집량 사용: %s", e)
    # 한도 판단(주 AI + 예비 AI)과 실행 기록은 run_pipeline 이 담당
    stats = run_pipeline(n, cfg["domains"], cfg["publish"])
    send_report_email(cfg, state, stats)
    _save_json(STATE_PATH, state)
    return stats


# ─────────────────────────── 대시보드용 조회 ───────────────────────────
def site_rows() -> list[dict]:
    """GitHub(content/posts) 글 목록 — 노션을 쓰지 않을 때 대시보드 데이터 원본."""
    tistory = {r.get("title"): r.get("url") for r in _load_json(ROOT / "memory" / "tistory_publish_log.json", [])
               if isinstance(r, dict)}
    rows = []
    cur = curation_state()
    why = curation_reasons()
    for f in POSTS_DIR.glob("*.json"):
        p = _load_json(f, {})
        if not p.get("title_ko"):
            continue
        rows.append({"제목": p["title_ko"], "도메인": p.get("domain", ""), "카테고리": p.get("category", ""),
                     "이미지": (p.get("media") or {}).get("image") or None,
                     "유형": p.get("topic", ""),
                     "상태": "Published" if tistory.get(p["title_ko"]) else "Collected",
                     "태그": ", ".join(p.get("tags") or []), "수집일": p.get("collected_at", ""),
                     "원문": p.get("url"), "티스토리": tistory.get(p["title_ko"]) or None,
                     "사이트": f"{SITE_URL}p/{f.stem}.html", "ID": f.stem,
                     "추천": cur.get(f.stem) == "pick", "숨김": cur.get(f.stem) == "hide",
                     "숨김 사유": why.get(f.stem, "")})
    rows.sort(key=lambda r: r["수집일"] or "", reverse=True)
    return rows


SITE_URL = "https://heo-j-h.github.io/3dflowhub/"


def fetch_dashboard_rows(limit: int = 500) -> list[dict]:
    client = _notion()
    if client is None:
        return site_rows()[:limit]
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
    if domains is None:  # 빈 목록([])은 '수집 안 함' — 전체 수집으로 바뀌지 않도록
        domains = list(DOMAINS)
    domains = [d for d in domains if d in DOMAINS]
    if not domains:
        log.info("선택된 수집 분야 없음 — 건너뜀")
        return {"at": datetime.now(timezone.utc).isoformat(), "collected": 0, "saved": 0, "published": 0,
                "drafts": 0, "publish_errors": 0, "errors": ["no domains selected"]}
    left = llm_budget_left()
    if left <= 0:  # 한도 소진 시 피드를 몇 분씩 긁지 않고 바로 알림 (실행 기록은 남김 → 대시보드에서 보임)
        stats = {"at": datetime.now(timezone.utc).isoformat(), "collected": 0, "saved": 0, "published": 0,
                 "drafts": 0, "publish_errors": 0, "llm_fallbacks": [],
                 "errors": [f"AI 일일 한도 소진 — {llm_reset_kst()} 이후 다시 시도 (예비 AI 키 없음)"]}
        reflect(stats, [])
        return stats
    notion = _notion()
    ensure_notion_schema(notion)
    seen = notion_existing_urls(notion) if notion else set()
    seen |= set(_published().keys())
    seen |= {url_hash(p["url"]) for f in POSTS_DIR.glob("*.json")  # GitHub 에 이미 있는 글
             if (p := _load_json(f, {})).get("url")}

    RUN_ERRORS.clear()  # 같은 프로세스에서 여러 번 실행해도 이번 실행 것만 집계
    items = collect(domains, max_items, seen)
    stats = {"at": datetime.now(timezone.utc).isoformat(), "collected": len(items),
             "saved": 0, "published": 0, "drafts": 0, "publish_errors": 0}

    budget = int(_load_json(CONFIG_PATH, {}).get("llm_daily_budget", 500))
    for idx, raw in enumerate(items):
        if llm_budget_left() <= 0:
            RUN_ERRORS.append(f"LLM 일일 한도({budget}회) 도달 — 남은 {len(items) - idx}건은 다음 날")
            break
        try:
            item = summarize(raw)
            if not item:
                continue
            page_id = save_to_notion(notion, item)
            item["notion_id"] = page_id or ""  # 브라우저 발행 후 노션 상태 갱신용
            item["related"] = related_posts(notion, item)  # 티스토리 본문 '함께 보면 좋은 글'
            save_post_json(item)  # GitHub Pages 게시판용 (발행 수 제한 없음)
            stats["saved"] += 1
            if publish:
                res = publish_to_tistory(item)
                if res["status"] == "published":
                    stats["published"] += 1
                    mark_notion_published(notion, page_id, res["url"])
                elif res["status"] == "draft_file":
                    stats["drafts"] += 1  # 초안 저장은 정상 경로 (브라우저 발행 대기)
        except LLMBudgetExceeded as e:
            RUN_ERRORS.append(f"{e} — 남은 {len(items) - idx}건은 리셋 후")
            break
        except Exception as e:  # 한 건의 실패가 전체를 죽이지 않도록
            log.exception("아이템 처리 실패 %s: %s", raw.get("url"), e)

    stats["offtopic"] = RUN_ERRORS.count("off-topic")  # 전략 평가 지표 (OPRO 궤적용)
    stats["short"] = RUN_ERRORS.count("short body")
    stats["prefiltered"] = RUN_ERRORS.count("prefiltered")
    stats["llm_fallbacks"] = [f["name"] for f in fallback_providers()]  # 등록된 예비 공급자 이름 (키 값은 기록 안 함)
    stats["strategy_ver"] = strategy_version(load_strategy().get("prompt_notes", []))
    stats["errors"] = list(dict.fromkeys(RUN_ERRORS))[:5]
    reflect(stats, [k for ks in LAST_KEYWORDS.values() for k in ks])
    pruned = prune_drafts()
    if pruned:
        log.info("오래된 티스토리 초안 %d개 정리", pruned)
    try:  # [4]→[5] 자아 성찰 후 전략·카테고리 체계 자동 업데이트
        import evolve
        evolve.evolve(stats)
    except Exception as e:
        log.warning("evolve 실패(다음 실행에 재시도): %s", e)
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
