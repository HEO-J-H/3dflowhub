"""디자이너 도구 — ① 홍보 이미지 렌더러 ② 사이트 디자인 스냅샷.

① AI 디자이너가 '문구·형식·테마·강조색'만 정하면 일관된 브랜드 템플릿으로 PNG 를 만든다
   (생성형 이미지가 아니라 타이포그래피 카드 — 저작권·품질이 안정적이고 무료).
   형식: square 1080×1080(인스타), x 1200×675(X·카드), story 1080×1920(스토리·쇼츠 표지)
   저장: drafts/promo/<id>.png (GitHub 실행이 커밋, 홍보 대기함에서 미리보기·다운로드, 14일 뒤 정리)
② 디자이너가 사이트를 '보는 눈': 디자인 토큰(색·글꼴·크기), 홈 구성, 콘텐츠 종류별 조회, 모바일 점검 결과
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import core

PROMO_DIR = core.ROOT / "drafts" / "promo"
SIZES = {"square": (1080, 1080), "x": (1200, 675), "story": (1080, 1920)}
THEMES = {  # 분야별 그라데이션 (사이트 og 카드와 같은 색)
    "default": ((0, 113, 227), (94, 92, 230)), "3d-dcc": ((0, 113, 227), (52, 199, 89)),
    "game-engine": ((94, 92, 230), (175, 82, 222)), "vfx": ((255, 69, 58), (255, 159, 10)),
    "ai-3d": ((48, 176, 199), (94, 92, 230)), "learn": ((52, 199, 89), (0, 113, 227)),
    "dark": ((28, 28, 30), (58, 58, 60)),
}
KO_FONTS = ["C:/Windows/Fonts/malgunbd.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
KO_FONTS_REG = ["C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]


def _font(size: int, bold: bool = True):
    for f in (KO_FONTS if bold else KO_FONTS_REG):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def has_korean_font() -> bool:
    return any(Path(f).exists() for f in KO_FONTS)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    """글자 폭 기준 줄바꿈 (한글은 글자 단위, 영어는 단어 단위)."""
    lines, cur = [], ""
    for token in re.findall(r"\S+\s*", text):
        trial = cur + token
        if d.textlength(trial.rstrip(), font=font) <= width:
            cur = trial
        elif d.textlength(token.rstrip(), font=font) > width:  # 긴 단어/한글 덩어리: 글자 단위
            for ch in token:
                if d.textlength((cur + ch).rstrip(), font=font) > width:
                    lines.append(cur.rstrip())
                    cur = ch
                else:
                    cur += ch
        else:
            lines.append(cur.rstrip())
            cur = token
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def render_promo(spec: dict, name: str) -> Path:
    """spec: {format, kicker(작은 머리말), headline(큰 문구), sub(보조 문구), points[최대3], theme, cta}"""
    fmt = spec.get("format") if spec.get("format") in SIZES else "square"
    W, H = SIZES[fmt]
    c1, c2 = THEMES.get(spec.get("theme"), THEMES["default"])
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):  # 세로 그라데이션
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    pad = int(W * 0.08)
    inner = W - pad * 2
    scale = W / 1080
    y = int(H * (0.12 if fmt != "x" else 0.10))
    if spec.get("kicker"):
        f = _font(int(38 * scale))
        kick = str(spec["kicker"])[:30]
        kw = d.textlength(kick, font=f)
        d.rounded_rectangle([pad, y, pad + kw + 44 * scale, y + 64 * scale], radius=int(32 * scale), fill=(255, 255, 255))
        d.text((pad + 22 * scale, y + 10 * scale), kick, font=f, fill=c1)
        y += int(110 * scale)
    size = int((92 if fmt != "x" else 70) * scale)
    f = _font(size)
    lines = _wrap(d, str(spec.get("headline", ""))[:60], f, inner)
    while len(lines) > (4 if fmt == "story" else 3) and size > 40:
        size -= 6
        f = _font(size)
        lines = _wrap(d, str(spec.get("headline", ""))[:60], f, inner)
    for ln in lines:
        d.text((pad, y), ln, font=f, fill=(255, 255, 255))
        y += int(size * 1.25)
    if spec.get("sub"):
        y += int(24 * scale)
        fs = _font(int((40 if fmt != "x" else 32) * scale), bold=False)
        for ln in _wrap(d, str(spec["sub"])[:120], fs, inner)[:3]:
            d.text((pad, y), ln, font=fs, fill=(235, 240, 255))
            y += int(fs.size * 1.4)
    pts = [str(p)[:40] for p in (spec.get("points") or [])][:3]
    if pts and fmt != "x":
        y += int(40 * scale)
        fp = _font(int(38 * scale))
        for p in pts:
            d.ellipse([pad, y + 14 * scale, pad + 18 * scale, y + 32 * scale], fill=(255, 255, 255))
            d.text((pad + 40 * scale, y), p, font=fp, fill=(255, 255, 255))
            y += int(64 * scale)
    fb = _font(int(34 * scale))
    d.text((pad, H - int(110 * scale)), "3dflowhub", font=fb, fill=(255, 255, 255))
    cta = str(spec.get("cta") or "프로필 링크에서 보기")[:24]
    cw = d.textlength(cta, font=fb)
    d.text((W - pad - cw, H - int(110 * scale)), cta, font=fb, fill=(235, 240, 255))
    PROMO_DIR.mkdir(parents=True, exist_ok=True)
    out = PROMO_DIR / f"{name}.png"
    img.save(out, optimize=True)
    return out


def site_snapshot() -> dict:
    """디자이너가 보는 사이트 정보 (화면을 직접 못 보므로 구조·토큰·성과로 전달)."""
    import build_site
    css = build_site.CSS
    tokens = dict(re.findall(r"--([a-z0-9-]+):([^;]+);", css.split("}")[0]))
    home_sections = ["히어로(배우기 중심 문구·버튼·통계)", "도구별 기초 배우기(도구 상자 그리드)", "에디터 추천",
                     "분야별 소식 게시판(그리드)", "도구별 정리 목록", "많이 본 글(순위)", "이번 주 요약 카드", "최신 글 카드",
                     "사이트 안내 링크", "전체 글 목록(페이지 번호)"]
    perf = (core._load_json(core.ROOT / "memory" / "performance.json", {}).get("pages") or {})
    learn = sorted((perf.get("learn") or {}).values(), key=lambda v: -v["views"])
    return {
        "design_tokens": {k: v.strip() for k, v in list(tokens.items())[:16]},
        "font": "시스템 산세리프(Apple SD Gothic Neo / Pretendard / Malgun Gothic), 본문 16px",
        "style": "Apple HIG 풍 — 흰 카드, 둥근 모서리 16~18px, 넓은 여백, 강조색 하나(#0071e3), 다크 모드 지원",
        "templates": ["홈", "기초 가이드 목록·상세(영상 맨 위·단계 카드·옵션 표)", "도구별 정리", "도구 게시판(소개 글·유형 칩)",
                      "글 상세", "주간 요약", "저장한 글", "404"],
        "home_sections_in_order": home_sections,
        "views_by_content_type_30d": perf.get("by_kind"),
        "top_guides": learn[:5], "least_viewed_guides": learn[-5:],
        "known_checks": "모바일 375px 가로 스크롤 없음, 내부 링크 깨짐 0, 이미지 없는 글은 도구 카드 썸네일 사용",
        "promo_image_formats": list(SIZES), "promo_themes": list(THEMES),
        "korean_font_available": has_korean_font(),
    }


if __name__ == "__main__":  # 견본 이미지 3장
    for fmt in SIZES:
        print(render_promo({"format": fmt, "kicker": "3ds Max 기초", "headline": "Bend 모디파이어로 파이프·배너 휘기",
                            "sub": "세그먼트 부족으로 꺾일 때 해결법까지, 영상과 따라 하기로", "theme": "3d-dcc",
                            "points": ["Angle·Direction·Axis", "Limits 로 일부만 휘기", "자주 하는 실수 2가지"]},
                           f"sample-{fmt}"))
