"""Blender 안에서 실행되는 레시피 애드온 실제 실행 검사 (화면 없이).

    blender -b --factory-startup --python tools/blender_check.py -- <addon.py> <result.json> [기대결과,쉼표구분]

1) 애드온 파일을 모듈로 불러와 register()
2) 테스트 장면: 회전·스케일이 적용 안 된 큐브 + 중복 정점이 있는 구 + 떨어진 정점이 있는 메시 (AI 생성물 흉내)
3) 애드온이 등록한 Operator 를 정의 순서대로 한 장면에서 실행 (파일 경로가 필요한 것은 임시 폴더로)
4) 기대 결과 확인 — 예외 없이 끝나도 결과가 틀리면 실패 (EXPECT 목록, 레시피가 약속한 것만 검사)
5) unregister() — 결과를 JSON 으로 저장. 하나라도 예외가 나면 ok=false
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
expect = [x for x in (argv[2] if len(argv) > 2 else "").split(",") if x]
save_path = Path(argv[3]) if len(argv) > 3 and argv[3] else None  # 통과하면 결과 장면을 .blend 예제 파일로 저장
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


def meshes():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _loose(o):
    used = {v for e in o.data.edges for v in e.vertices}
    return len(o.data.vertices) - len(used)


def _dupes(o):
    return len(o.data.vertices) - len({tuple(round(c, 4) for c in v.co) for v in o.data.vertices})


def _centered(o):
    from mathutils import Vector
    if not len(o.data.vertices):
        return True
    center = sum((v.co for v in o.data.vertices), Vector()) / len(o.data.vertices)
    return center.length < 1e-3


# 기대 결과 사전: 이름 → (설명, 검사 함수). recipes.EXPECT 와 이름이 같아야 함
EXPECT = {
    "transforms_applied": ("회전·스케일 적용", lambda ctx: all(
        max(abs(r) for r in o.rotation_euler) < 1e-4 and max(abs(c - 1) for c in o.scale) < 1e-4 for o in meshes())),
    "no_loose_verts": ("떨어진 정점 없음", lambda ctx: all(_loose(o) == 0 for o in meshes())),
    "no_duplicate_verts": ("겹친 정점 없음", lambda ctx: all(_dupes(o) == 0 for o in meshes())),
    "keeps_objects": ("메시 개수 유지", lambda ctx: len(meshes()) >= ctx["meshes_before"]),
    "has_material": ("모든 메시에 재질", lambda ctx: all(any(s.material for s in o.material_slots) for o in meshes())),
    "origin_centered": ("원점이 형상 중심", lambda ctx: all(_centered(o) for o in meshes())),
    "exported_file": ("파일 내보내기", lambda ctx: any(Path(ctx["tmp"]).rglob("*.*"))),
}


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
    test_scene()
    ctx = {"tmp": tmp, "meshes_before": len(meshes())}
    for cls in ops:
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
    for name in expect:
        if name not in EXPECT:
            step(f"기대:{name}", False, "알 수 없는 기대 결과")
            continue
        label, fn = EXPECT[name]
        try:
            step(f"기대:{label}", bool(fn(ctx)), "" if fn(ctx) else f"실행 후에도 '{label}' 이 충족되지 않음")
        except Exception:
            step(f"기대:{label}", False, traceback.format_exc())
    if save_path and all(s["ok"] for s in result["steps"]):
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(save_path), compress=True, copy=True)
            result["example"] = save_path.name
        except Exception:
            result["example_error"] = traceback.format_exc()[-300:]
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
