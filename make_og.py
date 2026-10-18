"""공유 미리보기 이미지(og:image) 생성 — 대표 이미지가 없는 글·페이지용 (1200×630, 분야별 1장).
한 번 만들어 static/og/ 에 커밋해 두면 된다: python make_og.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "static" / "og"
W, H = 1200, 630
FONT = next((f for f in ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
             if Path(f).exists()), None)
ITEMS = {  # 파일명: (분야, 한 줄 설명, 그라데이션 시작색, 끝색)
    "default": ("3D · Game Engine · VFX · AI 3D", "News, tool roundups & basics guides", (0, 113, 227), (94, 92, 230)),
    "3d-dcc": ("3D DCC", "Blender · 3ds Max · Maya · Houdini", (0, 113, 227), (52, 199, 89)),
    "game-engine": ("Game Engine", "Unreal Engine · Unity · Godot", (94, 92, 230), (175, 82, 222)),
    "vfx": ("VFX", "Compositing · Simulation · Motion graphics", (255, 69, 58), (255, 159, 10)),
    "ai-3d": ("AI 3D", "Gaussian splatting · NeRF · Text-to-3D", (48, 176, 199), (94, 92, 230)),
    "learn": ("Basics Guides", "Modifiers · Menus · Nodes — with videos", (52, 199, 89), (0, 113, 227)),
}


def font(size):
    return ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()


def make(name, title, sub, c1, c2):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for x in range(W):  # 대각 그라데이션 근사 (가로)
        t = x / (W - 1)
        d.line([(x, 0), (x, H)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    # 로고(큐브)
    cx, cy, s = 150, 175, 70
    top = [(cx, cy - s), (cx + s, cy - s // 2), (cx, cy), (cx - s, cy - s // 2)]
    left = [(cx - s, cy - s // 2), (cx, cy), (cx, cy + s), (cx - s, cy + s // 2)]
    right = [(cx + s, cy - s // 2), (cx, cy), (cx, cy + s), (cx + s, cy + s // 2)]
    d.polygon(top, fill=(255, 255, 255))
    d.polygon(left, fill=(225, 232, 255))
    d.polygon(right, fill=(190, 205, 250))
    d.text((250, 130), "3dflowhub", font=font(78), fill=(255, 255, 255))
    d.text((90, 330), title, font=font(92), fill=(255, 255, 255))
    d.text((92, 450), sub, font=font(40), fill=(235, 240, 255))
    d.text((92, 545), "heo-j-h.github.io/3dflowhub", font=font(30), fill=(220, 228, 255))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png", optimize=True)


# ── 도구별 썸네일 (대표 이미지 없는 글의 카드·공유 이미지) ─────────────────────
DOMAIN_COLORS = {k: (v[2], v[3]) for k, v in ITEMS.items()}
KO_FONT = next((f for f in ["C:/Windows/Fonts/malgunbd.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]
                if Path(f).exists()), None)


def tool_slug(name: str) -> str:
    import hashlib
    import re
    if not name.isascii():  # 한글 등: 영문만 남기면 서로 겹칠 수 있어 해시 사용
        return "t-" + hashlib.md5(name.encode()).hexdigest()[:8]
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def make_tool(name: str, domain_slug: str) -> None:
    c1, c2 = DOMAIN_COLORS.get(domain_slug, DOMAIN_COLORS["default"])
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for x in range(W):
        t = x / (W - 1)
        d.line([(x, 0), (x, H)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    big = ImageFont.truetype(KO_FONT if (KO_FONT and not name.isascii()) else FONT, 110) if FONT else ImageFont.load_default()
    w = d.textlength(name, font=big)
    size = 110
    while w > W - 160 and size > 50:  # 긴 이름은 글자 크기 줄임
        size -= 8
        big = ImageFont.truetype(KO_FONT if (KO_FONT and not name.isascii()) else FONT, size)
        w = d.textlength(name, font=big)
    d.text(((W - w) / 2, H / 2 - size / 2 - 20), name, font=big, fill=(255, 255, 255))
    d.text((90, H - 90), "3dflowhub", font=font(36), fill=(235, 240, 255))
    img.save(OUT / f"tool-{tool_slug(name)}.png", optimize=True)


def make_tools() -> list[str]:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import core
    made = []
    for dom, tools in core.SEED_CATEGORIES.items():
        dslug = core.DOMAIN_META.get(dom, {}).get("slug", "default")
        for t in tools + list(core.load_categories().get(dom, [])):
            if t.startswith("기타") or (OUT / f"tool-{tool_slug(t)}.png").exists():
                continue
            make_tool(t, dslug)
            made.append(t)
    return made


if __name__ == "__main__":
    for k, v in ITEMS.items():
        make(k, *v)
    print("생성:", ", ".join(ITEMS), "| 도구:", ", ".join(make_tools()))
