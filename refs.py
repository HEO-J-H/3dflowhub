"""참고 페이지 — 검색으로 많이 찾아오는 두 가지를 '근거가 있는' 형태로 만든다.

① 오류 해결 (/fix/): 실제 오류 메시지 원문을 제목으로 — 원인 → 해결 순서 → 다시 안 생기게.
   Blender 파이썬 오류는 화면 없는 Blender 에서 '오류가 나는 코드'와 '고친 코드'를 실제로 실행해
   재현·해결을 확인한 뒤 ✔ 검증 표시 (recipe_check 워크플로가 실행).
② 버전별 바뀐 점 (/changes/): 공식 릴리스 노트 본문(+하위 페이지)을 근거로 한국어 정리 — 근거 없는 내용 금지.

저장: content/fixes/*.json, content/changes/*.json → build_site 가 페이지로. 하루 상한으로 몰아치기 방지.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

import core

FIX_DIR = core.ROOT / "content" / "fixes"
CHANGE_DIR = core.ROOT / "content" / "changes"
FIXES_DAILY_MAX = 6
UA = {"User-Agent": "Mozilla/5.0 (3dflowhub reference builder)"}

# (도구, 오류 메시지 원문, 한국어 제목, 재현 {"bad": 오류가 나는 코드, "good": 고친 코드} 또는 None)
# 재현 코드는 --factory-startup 장면(Cube·Camera·Light)에서 화면 없이 실행된다.
FIXES: list[tuple[str, str, str, dict | None]] = [
    ("Blender", "RuntimeError: Operator bpy.ops.object.mode_set.poll() Context missing active object",
     "mode_set.poll() Context missing active object — 편집 모드 전환이 안 될 때",
     {"bad": "import bpy\nfor o in bpy.context.view_layer.objects: o.select_set(False)\nbpy.context.view_layer.objects.active = None\nbpy.ops.object.mode_set(mode='EDIT')",
      "good": "import bpy\ncube = bpy.data.objects['Cube']\nbpy.context.view_layer.objects.active = cube\ncube.select_set(True)\nbpy.ops.object.mode_set(mode='EDIT')\nbpy.ops.object.mode_set(mode='OBJECT')"}),
    ("Blender", "AttributeError: 'NoneType' object has no attribute 'data'",
     "'NoneType' object has no attribute 'data' — 활성 오브젝트가 없을 때",
     {"bad": "import bpy\nbpy.context.view_layer.objects.active = None\nprint(bpy.context.active_object.data)",
      "good": "import bpy\nobj = bpy.context.active_object or bpy.data.objects.get('Cube')\nif obj is not None:\n    print(obj.data)"}),
    ("Blender", "KeyError: 'bpy_prop_collection[key]: key \"Cube.001\" not found'",
     "bpy_prop_collection key not found — 이름으로 오브젝트를 못 찾을 때",
     {"bad": "import bpy\nprint(bpy.data.objects['Cube.001'])",
      "good": "import bpy\nobj = bpy.data.objects.get('Cube.001')\nprint('없음' if obj is None else obj.name)"}),
    ("Blender", "TypeError: Converting py args to operator properties: enum \"WRONG\" not found in",
     "enum not found — 오퍼레이터 옵션 값이 틀렸을 때",
     {"bad": "import bpy\nbpy.ops.object.select_all(action='WRONG')",
      "good": "import bpy\nbpy.ops.object.select_all(action='DESELECT')"}),
    ("Blender", "AttributeError: Calling operator \"bpy.ops.mesh.primitive_cube_ad\" error, could not be found",
     "operator could not be found — 오퍼레이터 이름 오타·애드온 미활성",
     {"bad": "import bpy\nbpy.ops.mesh.primitive_cube_ad()",
      "good": "import bpy\nbpy.ops.mesh.primitive_cube_add()"}),
    ("Blender", "TypeError: bpy_struct: item.attr = val: enum \"BADMODE\" not found in",
     "bpy_struct enum not found — 속성에 없는 값을 넣었을 때",
     {"bad": "import bpy\nbpy.context.scene.render.engine = 'BADMODE'",
      "good": "import bpy\nbpy.context.scene.render.engine = 'CYCLES'"}),
    ("Blender", "Error: Python: Traceback ... Add-on not loaded: missing bl_info or register()", "애드온 설치 후 켜지지 않을 때 (bl_info·register 누락)", None),
    ("Blender", "Normals are flipped (black faces / inverted shading)", "면이 검게 보이거나 음영이 뒤집힐 때 — 노멀 뒤집힘", None),
    ("Blender", "Cycles: CUDA error: Out of memory", "Cycles CUDA error: Out of memory — GPU 메모리 부족", None),
    ("Blender", "Textures are pink (missing image files)", "텍스처가 분홍색으로 나올 때 — 이미지 경로 끊김", None),
    ("Blender", "Boolean modifier produces no result or holes", "Boolean 모디파이어 결과가 비거나 구멍 날 때", None),
    ("Blender", "Scale is not applied (modifiers and bevel look wrong)", "베벨·모디파이어가 이상할 때 — 스케일 미적용", None),
    ("3ds Max", "-- Unknown property: \"xxx\" in undefined", "MAXScript Unknown property in undefined — 대상이 없을 때", None),
    ("3ds Max", "-- Type error: Call needs function or class, got: undefined", "MAXScript Call needs function or class, got: undefined", None),
    ("3ds Max", "-- Runtime error: Cannot set property on deleted node", "MAXScript 삭제된 노드에 접근할 때", None),
    ("3ds Max", "Missing external files (bitmap path not found)", "누락된 외부 파일(텍스처 경로) 해결", None),
    ("3ds Max", "Application error: 3ds Max has encountered a problem and must close", "3ds Max 가 강제 종료될 때 점검 순서", None),
    ("3ds Max", "V-Ray: Out of memory during light cache", "V-Ray 메모리 부족 — Light Cache 단계", None),
    ("3ds Max", "FBX export: smoothing groups not exported", "FBX 내보내기 스무딩 그룹 문제", None),
    ("Maya", "# Error: RuntimeError: No object matches name", "Maya No object matches name — 이름 불일치", None),
    ("Maya", "# Error: line 1: Cannot find procedure", "Maya MEL Cannot find procedure", None),
    ("Maya", "Viewport 2.0 shows black or flickering objects", "Viewport 2.0 검게·깜빡이게 보일 때", None),
    ("Maya", "Arnold render is black or noisy", "Arnold 렌더가 검거나 노이즈가 심할 때", None),
    ("Unreal Engine", "Lighting needs to be rebuilt", "Lighting needs to be rebuilt 메시지 해결", None),
    ("Unreal Engine", "Shader compilation stuck (Compiling Shaders)", "셰이더 컴파일이 끝나지 않을 때", None),
    ("Unreal Engine", "Out of video memory trying to allocate a rendering resource", "Out of video memory — GPU 메모리 부족", None),
    ("Unreal Engine", "Nanite mesh not displaying correctly", "Nanite 메시가 이상하게 보일 때", None),
    ("Unreal Engine", "Failed to package project (UATHelper error)", "프로젝트 패키징 실패 (UATHelper) 점검", None),
    ("Houdini", "Error: Invalid source (Copy to Points / Object Merge)", "Houdini Invalid source 오류", None),
    ("Houdini", "VEX error: Read-only expression given for read/write parameter", "VEX Read-only expression 오류", None),
    ("Substance 3D", "Substance Painter: baking produces artifacts or black areas", "Substance Painter 베이킹 얼룩·검은 부분", None),
    ("ZBrush", "ZBrush: Divide button greyed out (cannot subdivide)", "ZBrush Divide 가 비활성일 때", None),
    ("NVIDIA Omniverse", "Omniverse Launcher no longer available (deprecated)", "Omniverse 런처가 없어졌을 때 — 지금 설치하는 법", None),
    ("NVIDIA Omniverse", "USD export has missing textures in Omniverse", "USD 로 보냈더니 텍스처가 없을 때", None),
]

# (도구, 버전, 공식 릴리스 노트 주소)
CHANGES: list[tuple[str, str, str]] = [
    ("Blender", "4.2 LTS", "https://developer.blender.org/docs/release_notes/4.2/"),
    ("Blender", "4.3", "https://developer.blender.org/docs/release_notes/4.3/"),
    ("Blender", "4.4", "https://developer.blender.org/docs/release_notes/4.4/"),
    ("Blender", "4.5 LTS", "https://developer.blender.org/docs/release_notes/4.5/"),
    ("Blender", "5.0", "https://developer.blender.org/docs/release_notes/5.0/"),
    ("Blender", "5.1", "https://developer.blender.org/docs/release_notes/5.1/"),
    ("Houdini", "20.5", "https://www.sidefx.com/docs/houdini/news/20_5/"),
    ("Houdini", "21", "https://www.sidefx.com/docs/houdini/news/21/"),
    ("Godot", "4.x 최신", "https://godotengine.org/releases/"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rid(*parts: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", " ".join(parts).lower()).strip("-")[:50]
    return base + "-" + hashlib.md5("|".join(parts).encode()).hexdigest()[:5]


def load(kind: str) -> list[dict]:
    d = FIX_DIR if kind == "fix" else CHANGE_DIR
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


# ─────────────────────────── 근거 텍스트 ───────────────────────────
def page_text(url: str, limit: int = 14000, follow: int = 8) -> str:
    """공식 페이지 본문 + 같은 경로 아래 하위 페이지 몇 개 (Blender 릴리스 노트는 분야별 하위 페이지로 나뉨)."""
    from bs4 import BeautifulSoup

    def one(u: str) -> tuple[str, list[str]]:
        try:
            r = requests.get(u, headers=UA, timeout=20)
            if not r.ok:
                return "", []
        except requests.RequestException:
            return "", []
        soup = BeautifulSoup(r.text, "html.parser")
        links = [urljoin(u, a["href"]).split("#")[0] for a in soup.select("a[href]")]
        for t in soup(["script", "style", "nav", "header", "footer", "aside"]):
            t.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return re.sub(r"\s+", " ", main.get_text(" ", strip=True)), links

    text, links = one(url)
    subs = [l for l in dict.fromkeys(links) if l.startswith(url) and l.rstrip("/") != url.rstrip("/")][:follow]
    for s in subs:
        if len(text) >= limit:
            break
        t, _ = one(s)
        text += f"\n[{s.rsplit('/', 2)[-2]}] " + t
    return text[:limit]


# ─────────────────────────── 생성 ───────────────────────────
def _ask(prompt: str, tokens: int = 1800) -> dict:
    try:
        return core._parse_json(core.llm(prompt, system="You are a senior 3D technical director writing precise Korean help pages."
                                         + core.playbook("common", limit=3000), max_tokens=tokens, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:
        core.log.warning("참고 페이지 생성 실패: %s", e)
        return {}


def make_fix(tool: str, error: str, title: str, repro: dict | None) -> dict | None:
    prompt = (
        f"Write a Korean troubleshooting page for this {tool} error message:\n{error}\n"
        + (f"Verified reproduction (Blender, headless): this code raises the error:\n{repro['bad']}\n"
           f"and this fixed code runs without error:\n{repro['good']}\nExplain using exactly this cause and fix.\n" if repro else
           "Use only well-established, version-independent facts. If unsure about a detail, leave it out.\n")
        + "Keep official English UI/API names. Return JSON:\n"
          ' "summary": 1-2 sentences — what the message means,\n'
          ' "causes": 2-4 strings — common causes (most likely first),\n'
          ' "steps": 3-7 strings — how to fix, in order (menu paths / code),\n'
          ' "check": 1-2 strings — how to confirm it is fixed,\n'
          ' "prevent": 1-3 strings — how to avoid it next time,\n'
          ' "keywords": up to 5 Korean search phrases people type for this problem'
    )
    out = _ask(prompt)
    if not out.get("steps") or len(out.get("causes") or []) < 1:
        return None
    fx = core.fix_terms
    lst = lambda k, n: [fx(str(x)) for x in (out.get(k) or []) if x][:n]  # noqa: E731
    return {"id": rid(tool, error), "kind": "fix", "tool": tool, "error": error, "title": fx(title),
            "summary": fx(str(out.get("summary", ""))), "causes": lst("causes", 4), "steps": lst("steps", 7),
            "check": lst("check", 2), "prevent": lst("prevent", 3), "keywords": lst("keywords", 5),
            "repro": repro, "verified": None, "at": _now()}


def make_change(tool: str, version: str, url: str) -> dict | None:
    src = page_text(url)
    if len(src) < 600:
        core.log.warning("릴리스 노트를 읽지 못함: %s", url)
        return None
    prompt = (
        f"Official release notes of {tool} {version} (ground truth — use ONLY facts in this text):\n{src}\n\n"
        "Write a Korean summary for working artists. Return JSON:\n"
        ' "summary": 2-3 sentences — the most important changes,\n'
        ' "highlights": 6-12 {"area": e.g. Modeling/Rendering/Animation/Python API, "change": what changed, '
        '"why": one line — what it means for an artist},\n'
        ' "breaking": up to 5 strings — things that may break old files/scripts/add-ons (empty if none in the text),\n'
        ' "keywords": up to 5 Korean search phrases'
    )
    out = _ask(prompt, 2600)
    hl = [h for h in (out.get("highlights") or []) if isinstance(h, dict) and h.get("change")]
    if len(hl) < 4:
        return None
    fx = core.fix_terms
    return {"id": rid(tool, version), "kind": "change", "tool": tool, "version": version, "source": url,
            "title": f"{tool} {version} 바뀐 점 정리", "summary": fx(str(out.get("summary", ""))),
            "highlights": [{"area": str(h.get("area", ""))[:30], "change": fx(str(h["change"]))[:300],
                            "why": fx(str(h.get("why", "")))[:200]} for h in hl[:12]],
            "breaking": [fx(str(x)) for x in (out.get("breaking") or []) if x][:5],
            "keywords": [str(x) for x in (out.get("keywords") or [])][:5], "at": _now()}


def write(max_fixes: int = 2, max_changes: int = 1) -> list[str]:
    """아직 없는 페이지를 조금씩 (오류 해결은 하루 상한, 바뀐 점은 남은 것부터)."""
    if not core.background_ok(max_fixes + max_changes):
        return []
    have = {f.stem for d in (FIX_DIR, CHANGE_DIR) if d.exists() for f in d.glob("*.json")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    made_today = sum(1 for x in load("fix") if x.get("at", "").startswith(today))
    done = []
    for t in [t for t in FIXES if rid(t[0], t[1]) not in have][:max(0, min(max_fixes, FIXES_DAILY_MAX - made_today))]:
        try:
            p = make_fix(*t)
        except core.LLMBudgetExceeded:
            break
        if p:
            core._save_json(FIX_DIR / f"{p['id']}.json", p)
            done.append(p["title"])
    for t in [t for t in CHANGES if rid(t[0], t[1]) not in have][:max_changes]:
        try:
            p = make_change(*t)
        except core.LLMBudgetExceeded:
            break
        if p:
            core._save_json(CHANGE_DIR / f"{p['id']}.json", p)
            done.append(p["title"])
    return done


# ─────────────────────────── Blender 재현 검증 ───────────────────────────
def run_repro(code: str, timeout: int = 120) -> tuple[bool, str]:
    """화면 없는 Blender 에서 코드를 실행 → (오류 없이 끝났나, 오류 메시지)."""
    import recipes
    exe = recipes.blender_bin()
    if not exe:
        return None, "Blender 없음"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.py"
        f.write_text("import sys, traceback\ntry:\n" + "\n".join("    " + l for l in code.splitlines())
                     + "\nexcept Exception:\n    traceback.print_exc()\n    sys.exit(3)\n", encoding="utf-8")
        try:
            r = subprocess.run([exe, "-b", "--factory-startup", "--python-exit-code", "4", "--python", str(f)],
                               capture_output=True, text=True, timeout=timeout, errors="replace")
        except subprocess.TimeoutExpired:
            return False, "시간 초과"
        return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def verify_fixes(limit: int = 20) -> list[str]:
    """재현 코드가 있는 오류 페이지: 나쁜 코드는 그 오류로 실패하고, 고친 코드는 성공해야 ✔."""
    out = []
    for p in [p for p in load("fix") if p.get("repro") and p.get("verified") is None][:limit]:
        bad_ok, bad_log = run_repro(p["repro"]["bad"])
        if bad_ok is None:
            return out
        good_ok, good_log = run_repro(p["repro"]["good"])
        key = re.split(r"[:(]", p["error"], 1)[0].strip()  # 예: RuntimeError, AttributeError
        reproduced = (bad_ok is False) and key.split()[0] in bad_log
        p["verified"] = bool(reproduced and good_ok)
        p["verify_log"] = {"bad": bad_log[-400:], "good": good_log[-300:], "at": _now()}
        core._save_json(FIX_DIR / f"{p['id']}.json", p)
        out.append(f"{'✔' if p['verified'] else '✘'} {p['title']}")
    return out


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        print(verify_fixes())
    else:
        print(write(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
