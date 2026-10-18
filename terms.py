"""용어집: 음역·오번역된 3D 도구 이름을 정식 영문 표기로 교정 (예: 맥로스크립트 → MacroScript).
기본 사전(GLOSSARY) + 사용자 설정(config.json glossary) + 자동 학습(memory glossary_learned)."""
from __future__ import annotations

import re

# ─────────────────────────── 용어집 (오번역·음역 교정) ───────────────────────────
# 정식 표기 → (잘못된 변형 정규식, 검색용 한글 별칭 태그). 소프트웨어·플러그인·스크립트 언어 이름은 영문 정식 표기 유지.
GLOSSARY: dict[str, tuple[str, str]] = {
    "MacroScript": (r"맥로\s?스크립트|매크로\s?스크립트|Macro\s?script", "매크로스크립트"),
    "MAXScript": (r"맥스\s?스크립트|맥스크립트|Max\s?[Ss]cript|MAX\s?script|Maxscript", "맥스스크립트"),
    "3ds Max": (r"3[Dd][Ss]\s?맥스|3D\s?스튜디오\s?맥스|3DS\s?MAX|3ds\s?max|3DsMax|3dsMax", "3ds 맥스"),
    "Blender": (r"블렌더", "블렌더"),
    "Unreal Engine": (r"언리얼\s?엔진", "언리얼 엔진"),
    "Unreal": (r"언리얼(?!\s?엔진)", ""),
    "Unity": (r"유니티", "유니티"),
    "Houdini": (r"후디니|후디나", "후디니"),
    "ZBrush": (r"지브러시|제트브러시|Z-?brush", "지브러시"),
    "Cinema 4D": (r"시네마\s?4D|C4D", "시네마4D"),
    "V-Ray": (r"브이레이|V-?ray|Vray", "브이레이"),
    "Corona Renderer": (r"코로나\s?렌더러", "코로나 렌더러"),
    "Substance 3D": (r"서브스턴스(?:\s?3D)?", "서브스턴스"),
    "Geometry Nodes": (r"지오메트리\s?노드", "지오메트리 노드"),
    "After Effects": (r"애프터\s?이펙트(?:스)?", "애프터 이펙트"),
    "Nuke": (r"(?<![가-힣])누크(?![가-힣])", "누크"),
    "Maya": (r"(?<![가-힣])마야(?=\s|\(|에서|의|로|는|와|에|,|\.|$)", "마야"),
    "Godot": (r"고도\s?엔진|고닷", "고도 엔진"),
    "Marvelous Designer": (r"마블러스(?:\s?디자이너)?", "마블러스 디자이너"),
    "MetaHuman": (r"메타\s?휴먼", "메타휴먼"),
    "Nanite": (r"나나이트", "나나이트"),
    "Lumen": (r"(?<![가-힣])루멘(?![가-힣])", ""),
    "RailClone": (r"레일\s?클론", "레일클론"),
    "Forest Pack": (r"포레스트\s?팩", "포레스트팩"),
    "tyFlow": (r"타이\s?플로우|티와이\s?플로우|Tyflow|TyFlow", "타이플로우"),
    "Octane Render": (r"옥테인(?:\s?렌더(?:러)?)?", "옥테인 렌더"),
    "Redshift": (r"레드\s?시프트", "레드시프트"),
    "Arnold": (r"아놀드\s?렌더러|아놀드(?=\s?렌더)", "아놀드 렌더러"),
    "Quixel Megascans": (r"퀵셀\s?메가스캔|메가스캔", "메가스캔"),
    "Python": (r"파이썬", "파이썬"),
}
_GLOSS_RE = [(re.compile(v), k) for k, (v, _) in GLOSSARY.items()]


def glossary_extra() -> dict[str, str]:
    """config.json 의 glossary 로 사용자 용어 추가: {"정식표기": "변형1|변형2"}."""
    import core  # 설정·메모리 경로는 core 기준 (테스트에서 바뀌어도 따라감)
    g = dict(core._load_json(core.CONFIG_PATH, {}).get("glossary") or {})
    # evolve.audit_terms 가 학습한 '한글 음역 → 영문' (사용자 설정이 우선)
    for hangul, canon in (core.load_memory().get("glossary_learned") or {}).items():
        if not (isinstance(hangul, str) and isinstance(canon, str)):
            continue
        # 단어 전체만 교정 (앞은 한글이 아니고, 뒤는 조사·공백·문장부호) → '스타일' 같은 다른 단어 훼손 방지
        rx = rf"(?<![가-힣]){re.escape(hangul)}(?=(?:은|는|이|가|을|를|의|에|와|과|로|으로|에서|도|만|$|[^가-힣]))"
        g[canon] = f"{g[canon]}|{rx}" if canon in g else rx
    return {k: v for k, v in g.items() if isinstance(k, str) and isinstance(v, str) and v}


def fix_terms(text: str) -> str:
    """음역·오번역된 도구 이름을 정식 표기로 교정하고 '정식(정식)' 같은 중복 괄호를 정리."""
    if not isinstance(text, str) or not text:
        return text
    for rx, canon in _GLOSS_RE + [(re.compile(v), k) for k, v in glossary_extra().items()]:
        text = rx.sub(canon, text)
    # "Blender(Blender)", "MAXScript (MAXScript)" → 한 번만
    text = re.sub(r"([A-Za-z0-9][\w\- .]{1,30}?)\s?\(\s?\1\s?\)", r"\1", text)
    return text


def term_aliases(text: str) -> list[str]:
    """본문에 등장한 정식 표기의 한글 별칭 → 검색 태그 (예: Blender → 블렌더)."""
    return [alias for canon, (_, alias) in GLOSSARY.items() if alias and canon in (text or "")]


def apply_glossary(data: dict) -> dict:
    for key in ("title_ko", "summary", "insight"):
        data[key] = fix_terms(data.get(key) or "")
    for sct in data.get("sections") or []:
        sct["heading"], sct["body"] = fix_terms(sct.get("heading", "")), fix_terms(sct.get("body", ""))
    for f in data.get("faq") or []:
        if isinstance(f, dict):
            f["q"], f["a"] = fix_terms(f.get("q", "")), fix_terms(f.get("a", ""))
    raw_tags = data.get("tags") or []
    if isinstance(raw_tags, str):  # LLM 이 "a, b, c" 문자열로 줄 때
        raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    tags = [fix_terms(t) for t in raw_tags if isinstance(t, str)]
    blob = " ".join([data.get("title_ko", ""), data.get("summary", "")] + tags)
    data["tags"] = list(dict.fromkeys(tags + term_aliases(blob)))[:10]
    return data
