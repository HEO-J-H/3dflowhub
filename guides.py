"""기초 가이드 — DCC 툴의 기본 기능(모디파이어·메뉴·패널·노드)을 '영상 + 단계별 사용법 + 예시'로 정리하는 상시 레퍼런스.

새 소식(시간이 지나면 낡음)과 달리 오래 검색되는 에버그린 콘텐츠. 디자이너는 글보다 영상·이미지를 선호하므로
페이지 맨 위에 튜토리얼 영상(유튜브 임베드)을 두고, 글은 '언제 쓰나 → 따라하기 → 주요 옵션 → 활용 예시 → 자주 하는 실수' 순.

- 영상: 유튜브 검색(키 불필요) → oEmbed 로 임베드 가능 여부·제목·채널 확인 (원본은 유튜브에서 재생, 저작권 안전)
- 근거: 문서 주소를 알 수 있는 툴(Blender·Houdini)은 공식 문서 본문을 AI 에 함께 보여줌, 나머지는 공식 문서 검색 링크
- 생성: 하루 몇 개씩 (AI 한도 여유 있을 때만), content/guides/*.json → build_site 가 /learn/ 페이지로
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests

import core

GUIDE_DIR = core.ROOT / "content" / "guides"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}

BL = "https://docs.blender.org/manual/en/latest/"
HOU = "https://www.sidefx.com/docs/houdini/nodes/sop/"

# (도구, 분류, 영문 이름, 한국어 제목, 공식 문서 URL 또는 None)
CATALOG: list[tuple[str, str, str, str, str | None]] = [
    # 3ds Max — 모디파이어
    ("3ds Max", "모디파이어", "Edit Poly modifier", "Edit Poly 모디파이어 — 폴리곤 모델링의 기본", None),
    ("3ds Max", "모디파이어", "TurboSmooth modifier", "TurboSmooth — 부드러운 서브디비전", None),
    ("3ds Max", "모디파이어", "Bend modifier", "Bend — 오브젝트 휘게 하기", None),
    ("3ds Max", "모디파이어", "Twist modifier", "Twist — 비틀기", None),
    ("3ds Max", "모디파이어", "Taper modifier", "Taper — 끝을 좁히거나 넓히기", None),
    ("3ds Max", "모디파이어", "FFD modifier", "FFD — 격자로 자유 변형", None),
    ("3ds Max", "모디파이어", "Shell modifier", "Shell — 두께 만들기", None),
    ("3ds Max", "모디파이어", "Symmetry modifier", "Symmetry — 좌우 대칭 모델링", None),
    ("3ds Max", "모디파이어", "Chamfer modifier", "Chamfer — 모서리 깎기", None),
    ("3ds Max", "모디파이어", "UVW Map modifier", "UVW Map — 기본 UV 매핑", None),
    ("3ds Max", "모디파이어", "Unwrap UVW modifier", "Unwrap UVW — UV 펼치기", None),
    ("3ds Max", "모디파이어", "Sweep modifier", "Sweep — 스플라인 따라 단면 뽑기", None),
    ("3ds Max", "모디파이어", "Noise modifier", "Noise — 표면에 불규칙한 굴곡", None),
    ("3ds Max", "모디파이어", "Skin modifier", "Skin — 본에 메시 연결(스키닝)", None),
    ("3ds Max", "모디파이어", "Morpher modifier", "Morpher — 모프 타깃·표정", None),
    ("3ds Max", "모디파이어", "ProOptimizer modifier", "ProOptimizer — 폴리곤 수 줄이기", None),
    # 3ds Max — 메뉴·패널
    ("3ds Max", "메뉴·패널", "Command Panel and Modifier List", "커맨드 패널과 모디파이어 리스트 사용법", None),
    ("3ds Max", "메뉴·패널", "Modifier Stack", "모디파이어 스택 — 순서·끄기·합치기", None),
    ("3ds Max", "메뉴·패널", "Graphite Modeling Tools ribbon", "Graphite 모델링 툴(리본)", None),
    ("3ds Max", "메뉴·패널", "Slate Material Editor", "Slate 머티리얼 에디터", None),
    ("3ds Max", "메뉴·패널", "Render Setup dialog", "렌더 설정(Render Setup) 창", None),
    ("3ds Max", "메뉴·패널", "Scene Explorer and Layer Explorer", "씬 익스플로러·레이어 관리", None),
    ("3ds Max", "스크립트", "MAXScript Listener basics", "MAXScript 리스너 — 첫 스크립트 실행", None),
    # Blender — 모디파이어·에디터
    ("Blender", "모디파이어", "Subdivision Surface modifier", "Subdivision Surface — 부드러운 서브디비전",
     BL + "modeling/modifiers/generate/subdivision_surface.html"),
    ("Blender", "모디파이어", "Mirror modifier", "Mirror — 대칭 모델링", BL + "modeling/modifiers/generate/mirror.html"),
    ("Blender", "모디파이어", "Array modifier", "Array — 반복 복제", BL + "modeling/modifiers/generate/array.html"),
    ("Blender", "모디파이어", "Bevel modifier", "Bevel — 모서리 둥글게", BL + "modeling/modifiers/generate/bevel.html"),
    ("Blender", "모디파이어", "Solidify modifier", "Solidify — 두께 만들기", BL + "modeling/modifiers/generate/solidify.html"),
    ("Blender", "모디파이어", "Boolean modifier", "Boolean — 합치기·빼기", BL + "modeling/modifiers/generate/booleans.html"),
    ("Blender", "모디파이어", "Simple Deform modifier", "Simple Deform — 휘기·비틀기·테이퍼",
     BL + "modeling/modifiers/deform/simple_deform.html"),
    ("Blender", "모디파이어", "Shrinkwrap modifier", "Shrinkwrap — 표면에 달라붙이기",
     BL + "modeling/modifiers/deform/shrinkwrap.html"),
    ("Blender", "모디파이어", "Decimate modifier", "Decimate — 폴리곤 수 줄이기", BL + "modeling/modifiers/generate/decimate.html"),
    ("Blender", "에디터", "Shader Editor", "셰이더 에디터 — 노드로 재질 만들기", BL + "editors/shader_editor.html"),
    ("Blender", "에디터", "Outliner", "아웃라이너 — 씬 정리", BL + "editors/outliner/index.html"),
    ("Blender", "에디터", "Geometry Nodes basics", "지오메트리 노드 입문", BL + "modeling/geometry_nodes/introduction.html"),
    ("Blender", "에디터", "UV Editor unwrapping", "UV 에디터 — 펼치기 기본", BL + "editors/uv/index.html"),
    # Houdini — SOP 노드
    ("Houdini", "노드", "Scatter SOP", "Scatter — 표면에 점 뿌리기", HOU + "scatter.html"),
    ("Houdini", "노드", "Copy to Points SOP", "Copy to Points — 점마다 복제", HOU + "copytopoints.html"),
    ("Houdini", "노드", "Attribute Wrangle SOP", "Attribute Wrangle — VEX 한 줄로 속성 다루기", HOU + "attribwrangle.html"),
    ("Houdini", "노드", "PolyExtrude SOP", "PolyExtrude — 면 돌출", HOU + "polyextrude.html"),
    ("Houdini", "노드", "Boolean SOP", "Boolean — 합치기·빼기", HOU + "boolean.html"),
    # Unreal Engine
    ("Unreal Engine", "에디터", "Material Editor basics", "머티리얼 에디터 기본", None),
    ("Unreal Engine", "에디터", "Blueprint basics", "블루프린트 입문", None),
    ("Unreal Engine", "렌더링", "Nanite virtualized geometry", "Nanite — 고폴리곤을 그대로", None),
    ("Unreal Engine", "렌더링", "Lumen global illumination", "Lumen — 실시간 GI 설정", None),
    ("Unreal Engine", "에디터", "Sequencer cinematic", "시퀀서 — 시네마틱 만들기", None),
    # ── 2차 주제 (가이드 비중 50% 배분에 맞춰 확충, 문서 주소는 응답 확인함) ──
    ("3ds Max", "모델링", "Line spline and Lathe modifier", "Line·Lathe — 회전체(컵·병) 만들기", None),
    ("3ds Max", "모델링", "Extrude modifier for splines", "Extrude — 스플라인을 입체로", None),
    ("3ds Max", "모델링", "Array tool", "Array — 규칙적으로 복제·배열", None),
    ("3ds Max", "모델링", "Lattice modifier", "Lattice — 철골·와이어 구조 만들기", None),
    ("3ds Max", "메뉴·패널", "Track View Curve Editor", "Track View 커브 에디터 — 애니메이션 다듬기", None),
    ("3ds Max", "렌더링", "Arnold renderer basics in 3ds Max", "Arnold 렌더 기초 설정", None),
    ("Blender", "모델링", "Loop Cut and Slide", "Loop Cut — 엣지 루프 추가", BL + "modeling/meshes/editing/edge/loopcut_slide.html"),
    ("Blender", "모델링", "Proportional Editing", "Proportional Editing — 부드럽게 함께 움직이기",
     BL + "editors/3dview/controls/proportional_editing.html"),
    ("Blender", "모디파이어", "Screw modifier", "Screw — 회전체·나선 만들기", BL + "modeling/modifiers/generate/screw.html"),
    ("Blender", "모디파이어", "Lattice modifier", "Lattice — 격자로 형태 변형", BL + "modeling/modifiers/deform/lattice.html"),
    ("Blender", "모디파이어", "Weld modifier", "Weld — 겹친 정점 합치기", BL + "modeling/modifiers/generate/weld.html"),
    ("Blender", "리깅", "Weight Paint", "Weight Paint — 본 영향 칠하기", BL + "sculpt_paint/weight_paint/index.html"),
    ("Houdini", "노드", "VDB from Polygons SOP", "VDB from Polygons — 볼륨으로 변환", HOU + "vdbfrompolygons.html"),
    ("Houdini", "노드", "Remesh SOP", "Remesh — 고른 폴리곤으로 재구성", HOU + "remesh.html"),
    ("Houdini", "노드", "Sweep SOP", "Sweep — 커브 따라 단면 뽑기", HOU + "sweep.html"),
    ("Houdini", "노드", "Mountain SOP", "Mountain — 노이즈로 지형·변형", HOU + "mountain.html"),
    ("Unreal Engine", "에디터", "Landscape tool basics", "Landscape — 지형 만들기 기초", None),
    ("Unreal Engine", "이펙트", "Niagara particle system basics", "Niagara — 파티클 이펙트 입문", None),
    ("Unreal Engine", "렌더링", "Movie Render Queue", "Movie Render Queue — 고품질 영상 출력", None),
    ("Maya", "모델링", "Extrude and Bevel", "Extrude·Bevel — 폴리곤 모델링 기본기", None),
    ("Maya", "에디터", "Hypershade material editor", "Hypershade — 재질 만들기", None),
    ("ZBrush", "모델링", "DynaMesh", "DynaMesh — 형태를 자유롭게 늘리기", None),
    ("ZBrush", "모델링", "ZRemesher", "ZRemesher — 자동 리토폴로지", None),
    ("Substance 3D", "페인터", "Substance Painter baking mesh maps", "Substance Painter 맵 베이킹", None),
    # Maya · ZBrush · Substance
    ("Maya", "메뉴·패널", "Channel Box and Attribute Editor", "채널 박스·어트리뷰트 에디터", None),
    ("Maya", "모델링", "Multi-Cut tool", "Multi-Cut — 엣지 자르기·루프", None),
    ("ZBrush", "브러시", "ZBrush basic brushes", "ZBrush 기본 브러시", None),
    ("Substance 3D", "페인터", "Substance Painter layers and masks", "Substance Painter 레이어·마스크", None),
    # Blender 실무 기초 — 운영자가 정리해 둔 실무 주제 목록(2026-10)을 가이드로 (내용은 공식 문서 기준으로 새로 작성)
    ("Blender", "모델링", "Inset Faces", "Inset — 면 안쪽으로 면 넣기", BL + "modeling/meshes/editing/face/inset_faces.html"),
    ("Blender", "모델링", "Extrude Individual Faces", "Extrude Individual — 면마다 따로 밀어내기", BL + "modeling/meshes/editing/face/extrude_individual_faces.html"),
    ("Blender", "모델링", "Bevel tool (Ctrl+B)", "Bevel 도구 — 엣지·버텍스 챔퍼", BL + "modeling/meshes/editing/edge/bevel.html"),
    ("Blender", "모델링", "Bridge Edge Loops", "Bridge Edge Loops — 두 구멍 잇기", BL + "modeling/meshes/editing/edge/bridge_edge_loops.html"),
    ("Blender", "모델링", "Merge vertices (M)", "Merge — 버텍스 합치기", BL + "modeling/meshes/editing/mesh/merge.html"),
    ("Blender", "모델링", "Separate (P)", "Separate — 오브젝트 분리(디테치)", BL + "modeling/meshes/editing/mesh/separate.html"),
    ("Blender", "오브젝트", "Join (Ctrl+J)", "Join — 오브젝트 합치기(어태치)", BL + "scene_layout/object/editing/join.html"),
    ("Blender", "모델링", "Recalculate Normals (Shift+N)", "Normals — 면 방향 뒤집기·재계산", BL + "modeling/meshes/editing/mesh/normals.html"),
    ("Blender", "선택", "Select Linked (Ctrl+L)", "Select Linked — 연결된 덩어리(엘리먼트) 선택", BL + "modeling/meshes/selecting/linked.html"),
    ("Blender", "선택", "Checker Deselect", "Checker Deselect — 하나 건너 선택", BL + "modeling/meshes/selecting/checker_deselect.html"),
    ("Blender", "모델링", "Connect Vertex Path (J)", "Connect Vertex Path — 버텍스 사이 엣지 잇기", BL + "modeling/meshes/editing/vertex/connect_vertex_path.html"),
    ("Blender", "모델링", "Knife tool (K)", "Knife — 원하는 곳에 엣지 넣기", None),
    ("Blender", "모델링", "Edge Slide (GG)", "Edge Slide — 엣지 따라 버텍스 이동", BL + "modeling/meshes/editing/edge/edge_slide.html"),
    ("Blender", "오브젝트", "Set Origin", "Set Origin — 원하는 위치로 원점 옮기기", BL + "scene_layout/object/origin.html"),
    ("Blender", "기본 조작", "Snapping", "Snapping — 스냅 설정", BL + "editors/3dview/controls/snapping.html"),
    ("Blender", "기본 조작", "3D Cursor", "3D 커서 — 오브젝트를 원하는 위치로", BL + "editors/3dview/3d_cursor.html"),
    ("Blender", "기본 조작", "Transform Orientations", "Transform Orientation — 기즈모를 로컬·노멀 축으로", BL + "editors/3dview/controls/orientation.html"),
    ("Blender", "오브젝트", "Apply Transforms", "Apply — 스케일·회전 적용(리셋 엑스폼)", BL + "scene_layout/object/editing/apply.html"),
    ("Blender", "오브젝트", "Link/Transfer Data (copy modifiers)", "모디파이어를 다른 오브젝트에 복사", BL + "scene_layout/object/editing/link_transfer/index.html"),
    ("Blender", "기본 조작", "Viewport Overlays statistics", "뷰포트 오버레이 — 폴리곤 수·노멀 표시", BL + "editors/3dview/display/overlays.html"),
    ("Blender", "기본 조작", "Auto Save", "자동 저장 설정", BL + "editors/preferences/save_load.html"),
    ("Blender", "오브젝트", "Show/Hide (H)", "숨기기·보이기 (H / Alt+H)", BL + "scene_layout/object/editing/show_hide.html"),
    ("Blender", "모델링", "To Sphere", "To Sphere — 사각 면을 원형으로", BL + "modeling/meshes/editing/mesh/transform/to_sphere.html"),
    ("Blender", "모델링", "Triangles to Quads", "Tris to Quads — 삼각면을 사각면으로", BL + "modeling/meshes/editing/face/triangles_quads.html"),
    ("Blender", "모델링", "Curve modeling basics", "커브 모델링 기초", BL + "modeling/curves/introduction.html"),
    ("Blender", "텍스처", "Texture Paint brushes", "텍스처 페인트 — 브러시 설정", BL + "sculpt_paint/texture_paint/index.html"),
    ("Blender", "UV", "Export UV Layout", "UV 레이아웃 이미지로 내보내기", BL + "modeling/meshes/uv/editing.html"),
    ("Blender", "기본 조작", "Shade Smooth and Auto Smooth", "스무딩 — Shade Smooth·Auto Smooth(스무딩 그룹)", BL + "scene_layout/object/editing/shading.html"),
    ("Blender", "기본 조작", "Pivot Point (Individual Origins)", "피벗 포인트 — 면·오브젝트별로 각각 스케일", BL + "editors/3dview/controls/pivot_point/index.html"),
    ("Blender", "선택", "X-Ray select through", "X-Ray — 뒤쪽 점·선·면까지 선택", None),
    ("Blender", "기본 조작", "Clip Start and End", "뷰포트 클리핑 — 가까이 가면 잘릴 때", BL + "editors/3dview/sidebar.html"),
]

# 도구마다 100개 이상 — 확장 주제 (영문 이름이 이미 있으면 제외)
import guide_catalog  # noqa: E402

_have = {(t[0], t[2].lower()) for t in CATALOG}
CATALOG += [t for t in guide_catalog.topics() if (t[0], t[2].lower()) not in _have]

DOC_SEARCH = {
    "Blender": "https://docs.blender.org/manual/en/latest/search.html?q={q}",
    "Houdini": "https://www.sidefx.com/search/?q={q}",
    "NVIDIA Omniverse": "https://www.google.com/search?q=site%3Adocs.omniverse.nvidia.com+{q}",
    "3ds Max": "https://help.autodesk.com/view/3DSMAX/2026/ENU/?query={q}",
    "Maya": "https://help.autodesk.com/view/MAYAUL/2026/ENU/?query={q}",
    "Unreal Engine": "https://dev.epicgames.com/community/search?query={q}",
    "ZBrush": "https://help.maxon.net/search?q={q}",
    "Substance 3D": "https://helpx.adobe.com/search.html#q={q}",
}


def slug(tool: str, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{tool} {name}".lower()).strip("-")
    return base[:60] + "-" + hashlib.md5(f"{tool}|{name}".encode()).hexdigest()[:4]


def doc_link(tool: str, name: str, url: str | None) -> str:
    return url or DOC_SEARCH.get(tool, "https://www.google.com/search?q={q}").format(q=quote(f"{tool} {name}"))


def find_videos(query: str, n: int = 2) -> list[dict]:
    """유튜브 검색 → 임베드 가능한 영상 n개 (제목·채널은 oEmbed 로 확인)."""
    try:
        r = requests.get("https://www.youtube.com/results", params={"search_query": query}, headers=UA, timeout=20)
        ids = list(dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', r.text)))[:10]
    except requests.RequestException:
        return []
    out = []
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", query) if len(w) > 2 and w.lower() not in ("tutorial", "modifier")]
    for vid in ids:
        try:
            o = requests.get("https://www.youtube.com/oembed", timeout=15,
                             params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
            if not o.ok:  # 임베드 금지·삭제 영상
                continue
            meta = o.json()
        except (requests.RequestException, ValueError):
            continue
        title = meta.get("title", "")
        if words and sum(w in title.lower() for w in words) < min(2, len(words)):
            continue  # 주제와 덜 맞는 영상 제외
        out.append({"id": vid, "title": title, "author": meta.get("author_name", "")})
        if len(out) >= n:
            break
    return out


def _doc_text(url: str | None) -> str:
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body
        return re.sub(r"\s+", " ", main.get_text(" ") if main else "")[:6000]
    except Exception:
        return ""


DOC_IMAGE_LICENSE = {"docs.blender.org": ("Blender Manual", "CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")}


def doc_images(url: str | None, n: int = 3) -> list[dict]:
    """공식 문서의 그림(패널 스크린샷·예시) — 재사용이 허용된 문서(Blender 매뉴얼, CC BY-SA)만, 출처와 함께."""
    from urllib.parse import urljoin, urlparse
    if not url or urlparse(url).netloc not in DOC_IMAGE_LICENSE:
        return []
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"  # 헤더에 charset 이 없으면 latin-1 로 읽혀 글자가 깨짐
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.headerlink"):  # 문단 고정 링크(¶) 제거
        a.decompose()
    main = soup.find(attrs={"role": "main"}) or soup.body
    out = []
    for img in main.find_all("img") if main else []:
        src = img.get("src") or ""
        if "_images/" not in src or src.lower().endswith(".svg"):
            continue  # 로고·아이콘 제외
        fig = img.find_parent("figure")
        cap = fig.find("figcaption") if fig else None
        out.append({"src": urljoin(url, src), "alt": (img.get("alt") or "")[:120],
                    "caption": re.sub(r"\s+", " ", cap.get_text(" ", strip=True))[:160] if cap else "",
                    "source": url})
        if len(out) >= n:
            break
    return out


_KEY = re.compile(r"(?:Ctrl|Shift|Alt|Tab|Enter|Esc|Space|Delete|Home|UI|OK|F\d{1,2}|[A-Z])")  # 단축키는 경로 아님
_UI = re.compile(r"[A-Z][A-Za-z0-9]*(?:[ -][A-Z0-9][A-Za-z0-9]*)*")


def menu_path(steps: list[str], name: str, n: int = 6) -> list[str]:
    """단계 글에서 메뉴 경로(영문 UI 이름)를 순서대로 뽑아 도식용으로 (AI 호출 없음).
    기능 이름이 처음 나오는 단계까지만 — 그 뒤는 옵션 조절이라 경로가 아님."""
    key = name.split()[0].lower()
    path: list[str] = []
    for st in steps:
        for m in _UI.findall(st):
            m = m.strip()
            if len(m) > 1 and m not in path and not _KEY.fullmatch(m):
                path.append(m)
        if key in st.lower():
            break
    else:
        return []  # 경로 끝(기능 선택)이 안 보이면 도식 생략
    return path[:n] if len(path) >= 2 else []


def _text(x) -> str:
    """AI 가 문자열 대신 {"mistake":..,"fix":..} 같은 객체를 줄 때 '값 → 값' 으로."""
    if isinstance(x, dict):
        return " → ".join(str(v) for v in x.values() if v)
    return str(x)


def make_guide(tool: str, group: str, name: str, title_ko: str, url: str | None) -> dict | None:
    domain = next((d for d, cats in core.SEED_CATEGORIES.items() if any(tool in c for c in cats)), "3D DCC")
    videos = find_videos(f"{tool} {name} tutorial")
    doc = _doc_text(url)
    prompt = (
        f"Write a Korean beginner-to-intermediate reference guide for: {tool} — {name}.\n"
        + (f"Official documentation text (ground truth, prefer it):\n{doc}\n" if doc else
           "No documentation text available: use only well-established, version-independent facts; omit anything unsure.\n")
        + "Readers are Korean 3D artists who prefer visuals; keep text short and practical. Keep official English "
          "names for tools, menus and parameters (e.g. Modifier List, Segments, Angle).\nReturn JSON:\n"
          ' "summary": 1-2 sentences — what it does,\n'
          ' "when": 3 bullet strings — when to use it,\n'
          ' "steps": 4-7 short step strings — how to apply it from scratch (menu path / shortcut included),\n'
          ' "params": up to 6 {"name": English UI name, "desc": Korean one-line effect},\n'
          ' "examples": 2-3 {"title": Korean, "steps": 2-4 short strings} — concrete use cases (e.g. bending a pipe),\n'
          ' "mistakes": 2-3 strings, each "common mistake → how to fix",\n'
          ' "related": up to 4 related features (English names)'
    )
    try:
        out = core._parse_json(core.llm(prompt, system="You are a senior 3D instructor writing concise Korean docs."
                                        + core.playbook("common", "guide_writer", limit=4000),
                                        max_tokens=1600, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:
        core.log.warning("가이드 생성 실패 %s %s: %s", tool, name, e)
        return None
    if not isinstance(out, dict) or not out.get("steps"):
        return None
    fx = core.fix_terms

    def lst(key, n):
        return [fx(_text(x)) for x in (out.get(key) or []) if x][:n]

    return {
        "id": slug(tool, name), "tool": tool, "domain": domain, "group": group, "name": name,
        "title": fx(title_ko), "summary": fx(str(out.get("summary", ""))), "when": lst("when", 4),
        "steps": lst("steps", 8),
        "params": [{"name": str(p.get("name", ""))[:40], "desc": fx(str(p.get("desc", "")))[:160]}
                   for p in (out.get("params") or []) if isinstance(p, dict) and p.get("name")][:6],
        "examples": [{"title": fx(str(x.get("title", ""))), "steps": [fx(str(s)) for s in (x.get("steps") or [])][:5]}
                     for x in (out.get("examples") or []) if isinstance(x, dict) and x.get("title")][:3],
        "mistakes": lst("mistakes", 3), "related": [str(x)[:40] for x in (out.get("related") or [])][:4],
        "videos": videos, "doc": doc_link(tool, name, url), "grounded": bool(doc),
        "images": doc_images(url), "menu_path": menu_path(lst("steps", 8), name),
        "at": datetime.now(timezone.utc).isoformat(),
    }


def extra_topics() -> list[tuple]:
    """AI 관리자가 제안·수락된 주제 (strategy.json guide_topics)."""
    return [tuple(t) for t in core.load_strategy().get("guide_topics", []) if isinstance(t, list) and len(t) == 5]


def pending() -> list[tuple]:
    have = {p.stem for p in GUIDE_DIR.glob("*.json")} if GUIDE_DIR.exists() else set()
    todo = [t for t in CATALOG + extra_topics() if slug(t[0], t[2]) not in have]
    # 도구별로 번갈아 (한 도구만 몰아서 쓰지 않게) — 도구 안에서는 목록 순서 유지
    by_tool: dict[str, list] = {}
    for t in todo:
        by_tool.setdefault(t[0], []).append(t)
    out = []
    by_tool = dict(sorted(by_tool.items(), key=lambda kv: kv[0] not in guide_catalog.FIRST))
    while any(by_tool.values()):
        for q in by_tool.values():
            if q:
                out.append(q.pop(0))
    return out


GUIDES_DAILY_MAX = 40  # 기초 가이드 우선 (운영자 요청) — 품질 검사 통과분만, 하루 상한으로 몰아치기 방지


def passes_quality(g: dict) -> bool:
    """얇은 가이드는 올리지 않음: 따라하기 4단계 이상 + 옵션 설명 2개 이상 + (공식 문서 근거 또는 영상)."""
    return len(g.get("steps") or []) >= 4 and len(g.get("params") or []) >= 2 and bool(g.get("grounded") or g.get("videos"))


def write_guides(max_new: int = 4, gate: bool = True) -> list[str]:
    """아직 없는 주제를 생성. AI 할당 비중(guides 0.5)에 맞춰 기본 생성량 확대."""
    budget = int(core.load_config().get("llm_daily_budget", 500))
    if max_new <= 0 or (gate and core.llm_budget_left() < budget * 0.3):
        return []
    # AI 할당 비중 0.5 반영하여 하루 충분한 가이드 제작 허용
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    made_today = sum(1 for g in load_all() if (g.get("at") or "").startswith(today))
    max_new = min(max_new, max(0, int(core.load_config().get("guides_daily_max", GUIDES_DAILY_MAX)) - made_today))
    done = []
    for t in pending()[:max_new]:
        try:
            g = make_guide(*t)
        except core.LLMBudgetExceeded:
            break
        if g and not passes_quality(g):
            core.log.info("가이드 품질 미달로 저장 안 함: %s", t[3])
            continue
        if g:
            core._save_json(GUIDE_DIR / f"{g['id']}.json", g)
            done.append(g["title"])
    return done


def load_all() -> list[dict]:
    if not GUIDE_DIR.exists():
        return []
    gs = [core._load_json(f, None) for f in GUIDE_DIR.glob("*.json")]
    order = {slug(t[0], t[2]): i for i, t in enumerate(CATALOG)}
    for g in gs:
        if isinstance(g, dict):
            for k in ("when", "steps", "mistakes"):
                g[k] = [_text(x) for x in g.get(k) or []]
    return sorted([g for g in gs if isinstance(g, dict) and g.get("steps")],
                  key=lambda g: (g["tool"], order.get(g["id"], 999)))


if __name__ == "__main__":  # 수동 생성: python guides.py 3
    import sys
    print(json.dumps(write_guides(int(sys.argv[1]) if len(sys.argv) > 1 else 2), ensure_ascii=False))


def backfill_visuals(force: bool = False) -> int:
    """이미 만든 가이드에 문서 이미지·메뉴 경로 도식을 채움 (AI 호출 없음)."""
    done = 0
    for f in sorted(GUIDE_DIR.glob("*.json")) if GUIDE_DIR.exists() else []:
        g = core._load_json(f, {})
        if not g or (not force and "images" in g and "menu_path" in g):
            continue
        g["images"] = doc_images(g.get("doc"))
        g["menu_path"] = menu_path(g.get("steps", []), g.get("name", ""))
        core._save_json(f, g)
        done += 1
    return done
