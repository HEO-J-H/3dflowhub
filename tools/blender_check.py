"""Blender 안에서 실행되는 레시피 애드온 실제 실행 검사 (화면 없이).

    blender -b --factory-startup --python tools/blender_check.py -- <addon.py> <result.json>

1) 애드온 파일을 모듈로 불러와 register()
2) 테스트 장면: 회전·스케일이 적용 안 된 큐브 + 중복 정점이 있는 구 + 떨어진 정점이 있는 메시 (AI 생성물 흉내)
3) 애드온이 등록한 Operator 를 모두 실행 (파일 경로가 필요한 것은 임시 폴더로)
4) unregister() — 결과를 JSON 으로 저장. 하나라도 예외가 나면 ok=false
"""
import importlib.util
import json
import sys
import tempfile
import traceback
from pathlib import Path

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
addon_path, out_path = Path(argv[0]), Path(argv[1])
result = {"ok": False, "blender": bpy.app.version_string, "steps": [], "error": ""}


def step(name, ok, detail=""):
    result["steps"].append({"name": name, "ok": ok, "detail": str(detail)[-600:]})


def test_scene():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in list(bpy.data.objects):  # 장면 초기화 (등록된 애드온은 유지)
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add(location=(1, 2, 0), rotation=(0.3, 0, 0.5), scale=(2, 2, 2))
    bpy.ops.mesh.primitive_uv_sphere_add(location=(-2, 0, 0))
    sphere = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.duplicate()  # 겹친 중복 정점
    bpy.ops.object.mode_set(mode="OBJECT")
    me = bpy.data.meshes.new("loose")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (5, 5, 5)], [], [(0, 1, 2)])  # 떨어진 정점 1개
    obj = bpy.data.objects.new("AI_Generated_Mesh", me)
    bpy.context.scene.collection.objects.link(obj)
    for o in bpy.context.scene.objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = sphere


def main():
    spec = importlib.util.spec_from_file_location("recipe_addon", addon_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        mod.register()
        step("register", True)
    except Exception:
        step("register", False, traceback.format_exc())
        return
    ops = [c for c in vars(mod).values() if isinstance(c, type) and issubclass(c, bpy.types.Operator)
           and getattr(c, "bl_idname", "")]
    if not ops:
        step("operators", False, "애드온에 실행할 Operator 가 없음")
    tmp = tempfile.mkdtemp(prefix="recipe_")
    for cls in ops:
        test_scene()
        cat, name = cls.bl_idname.split(".", 1)
        op = getattr(getattr(bpy.ops, cat), name)
        kwargs = {}
        props = getattr(cls, "__annotations__", {})
        for key in ("filepath", "directory", "export_path", "output_path", "output_dir", "folder"):
            if key in props:
                kwargs[key] = tmp + ("/out.glb" if "file" in key else "/")
        try:
            if not op.poll():
                step(cls.bl_idname, False, "poll() 실패 — 테스트 장면(메시 선택됨)에서 실행 불가")
                continue
            res = op(**kwargs)
            step(cls.bl_idname, "CANCELLED" not in res, f"결과 {set(res)}, 오브젝트 {len(bpy.context.scene.objects)}개")
        except Exception:
            step(cls.bl_idname, False, traceback.format_exc())
    try:
        mod.unregister()
        step("unregister", True)
    except Exception:
        step("unregister", False, traceback.format_exc())
    result["ok"] = bool(result["steps"]) and all(s["ok"] for s in result["steps"])


try:
    main()
except Exception:
    result["error"] = traceback.format_exc()[-800:]
if not result["ok"] and not result["error"]:
    result["error"] = next((s["detail"] or s["name"] for s in result["steps"] if not s["ok"]), "검사 실패")
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
