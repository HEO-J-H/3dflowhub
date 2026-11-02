"""심화 매뉴얼 그림 — Blender 옵션 값을 바꿔 가며 실제로 렌더한 비교 이미지 (글보다 그림: 아티스트는 눈으로 본다).

AI 가 '이 옵션을 값 3개로 바꿔 보여주는' bpy 코드를 쓰고 → 화면 없는 Blender(Cycles CPU)에서 값마다 렌더 →
그림이 모두 만들어지고 서로 달라야(값을 바꿔도 똑같으면 실패) 통과. JPEG 로 static/manual/<id>/ 에 저장 → 매뉴얼 옵션 카드에.
실행: recipe_check 워크플로(Blender 설치됨) 또는 로컬 `python manual_shots.py`.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import core
import manual

IMG_DIR = core.ROOT / "static" / "manual"
PER_MANUAL = 3   # 매뉴얼마다 비교 그림을 만들 옵션 수
PER_RUN = 4      # 한 번 실행에 처리할 매뉴얼 수 (렌더 시간)

SCENE_NOTE = ("Blender is started with --factory-startup: scene has 'Cube' (2m, at origin), 'Camera' (at 7.36,-6.93,4.96 "
              "looking at origin), 'Light'. Your code may delete/replace the cube and add objects, modifiers, materials. "
              "Do not delete the camera or light (the harness re-frames the camera automatically on all meshes). "
              "Use bpy.ops.mesh.primitive_*_add operators or bpy.data API only. Do NOT render or save; "
              "the harness renders after your code. The value to demonstrate is in variable V.")

RENDER = """
import mathutils
sc = bpy.context.scene
# 카메라·조명이 없으면 다시 만들고, 보이는 메쉬 전체가 화면에 들어오게 자동 구도
cam = sc.camera or next((o for o in sc.objects if o.type == 'CAMERA'), None)
if cam is None:
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
    sc.collection.objects.link(cam)
sc.camera = cam
if not any(o.type == 'LIGHT' for o in sc.objects):
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sun.data.energy = 3.0
    sun.rotation_euler = (0.8, 0.2, 0.6)
    sc.collection.objects.link(sun)
bpy.context.view_layer.update()
pts = [o.matrix_world @ mathutils.Vector(c) for o in sc.objects if o.type in ('MESH', 'CURVE') and o.visible_get()
       for c in o.bound_box]
if pts:
    lo = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    mid, size = (lo + hi) / 2, max((hi - lo).length, 0.1)
    cam.data.lens = 50
    cam.location = mid + mathutils.Vector((1.0, -1.1, 0.75)).normalized() * size * 2.3
    cam.rotation_euler = (mid - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam.data.clip_end = max(100, size * 10)
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = 16
sc.cycles.use_denoising = False
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 480, 300, 100
sc.render.image_settings.file_format = 'JPEG'
sc.render.image_settings.quality = 82
if sc.world is None:
    sc.world = bpy.data.worlds.new('W')
sc.world.use_nodes = True
bg = sc.world.node_tree.nodes.get('Background')
if bg:
    bg.inputs[0].default_value = (0.32, 0.34, 0.38, 1)
    bg.inputs[1].default_value = 1.0
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
"""


def _plan(x: dict) -> list[dict]:
    opts = "\n".join(f"- {o['name']}: {o.get('effect', '')}" for o in x["options"])
    prompt = (f"Blender command: {x['name']}. Options:\n{opts}\n\n{SCENE_NOTE}\n"
              f"Pick up to {PER_MANUAL} options whose effect is clearly VISIBLE in a still render, and for each give 3 "
              "values that look clearly different. Return JSON {\"shots\": [{\"option\": exact option name from the list, "
              "\"values\": [3 Python literals], \"labels\": [3 short Korean labels like 'Width 0.1'], "
              "\"code\": \"bpy code (import bpy first) that builds the demo and applies V\"}]}. "
              "Use only Blender 4.x Python API that surely exists. Return {\"shots\": []} if nothing is visual.")
    try:
        out = core._parse_json(core.llm(prompt, system="You are an expert Blender Python technical artist.",
                                        max_tokens=2600, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("매뉴얼 그림 계획 실패 %s: %s", x["id"], e)
        return []
    return [s for s in out.get("shots") or [] if isinstance(s, dict) and s.get("code") and len(s.get("values") or []) == 3]


def _repair(code: str, log: str) -> str:
    try:
        out = core._parse_json(core.llm(
            f"This Blender 4.x Python code failed:\n{code}\n\nError:\n{log[-800:]}\n\n{SCENE_NOTE}\n"
            "Return JSON {\"code\": fixed code}.", system="You are an expert Blender Python technical artist.",
            max_tokens=1500, json_mode=True))
        return str(out.get("code") or "")
    except core.LLMBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001
        return ""


def _render(code: str, value, out_path: Path, timeout: int = 180) -> tuple[bool, str]:
    import recipes
    exe = recipes.blender_bin()
    if not exe:
        return False, "Blender 없음"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "shot.py"
        f.write_text(f"import bpy\nV = {value!r}\nOUT = {str(out_path)!r}\n{code}\n{RENDER}", encoding="utf-8")
        try:
            r = subprocess.run([exe, "-b", "--factory-startup", "--python-exit-code", "4", "--python", str(f)],
                               capture_output=True, text=True, timeout=timeout, errors="replace")
        except subprocess.TimeoutExpired:
            return False, "시간 초과"
    return r.returncode == 0 and out_path.exists(), (r.stdout + r.stderr)[-600:]


def shots_for(x: dict) -> list[dict]:
    d = IMG_DIR / x["id"]
    d.mkdir(parents=True, exist_ok=True)
    done = []
    for k, s in enumerate(_plan(x)):
        items, digests = [], set()
        for i, v in enumerate(s["values"]):
            p = d / f"{k}-{i}.jpg"
            ok, log = _render(s["code"], v, p)
            if not ok and i == 0:  # 첫 렌더 실패 → 오류를 보여주고 한 번 고쳐 쓰게
                s["code"] = _repair(s["code"], log) or s["code"]
                ok, log = _render(s["code"], v, p)
            if not ok:
                core.log.info("렌더 실패 %s/%s: %s", x["id"], s.get("option"), log[-200:])
                break
            digests.add(hashlib.md5(p.read_bytes()).hexdigest())
            labels = s.get("labels") or []
            items.append({"src": f"{x['id']}/{p.name}", "label": str(labels[i] if i < len(labels) else v)[:40]})
        if len(items) == 3 and len(digests) == 3:  # 값마다 그림이 달라야 '보여주는' 그림
            done.append({"option": str(s.get("option", ""))[:50], "items": items})
        else:
            for i in range(3):
                (d / f"{k}-{i}.jpg").unlink(missing_ok=True)
    if not done:
        d.rmdir() if d.exists() and not any(d.iterdir()) else None
    return done


def run(limit: int = PER_RUN) -> list[str]:
    todo = [x for x in manual.load_all() if x["tool"] == "Blender" and "shots" not in x][:limit]
    made = []
    for x in todo:
        try:
            x["shots"] = shots_for(x)
        except core.LLMBudgetExceeded:
            break
        core._save_json(manual.DIR / f"{x['id']}.json", x)
        made.append(f"{x['id']}: {len(x['shots'])}")
    return made


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else PER_RUN), ensure_ascii=False))
