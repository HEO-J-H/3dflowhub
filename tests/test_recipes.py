import recipes

ADDON = '''import bpy
bl_info = {"name": "T", "blender": (4, 0, 0), "category": "Object"}
class OBJECT_OT_t(bpy.types.Operator):
    bl_idname = "object.t"
    bl_label = "T"
    def execute(self, context):
        return {'FINISHED'}
def register():
    bpy.utils.register_class(OBJECT_OT_t)
def unregister():
    bpy.utils.unregister_class(OBJECT_OT_t)
'''


def test_blender_addon_ok():
    assert recipes.check_script("python", "Blender", ADDON) == ""


def test_blender_missing_register():
    assert "필수" in recipes.check_script("python", "Blender", ADDON.replace("def unregister", "def other"))


def test_python_syntax_and_network_rejected():
    assert "문법" in recipes.check_script("python", "Maya", ADDON + "\ndef broken(:\n")
    assert "네트워크" in recipes.check_script("python", "Maya", ADDON + "\nimport requests\n")


def test_maxscript_brackets():
    ok = 'macroScript T category:"3dflowhub" (\n  for o in selection do (\n    print o.name -- (comment\n  )\n)\n' * 2
    assert recipes.check_script("maxscript", "3ds Max", ok) == ""
    assert "괄호" in recipes.check_script("maxscript", "3ds Max", ok + "(")
    assert "외부" in recipes.check_script("maxscript", "3ds Max", ok + 'DOSCommand "x"')


def test_blender_recipe_published_only_after_runtime_ok():
    assert not recipes.published({"host": "Blender"})
    assert recipes.published({"host": "Blender", "runtime": {"ok": True}})
    assert recipes.published({"host": "3ds Max"})


def test_no_blender_means_no_verdict(monkeypatch):
    monkeypatch.setattr(recipes, "blender_bin", lambda: None)
    assert recipes.run_blender_check("x")["ok"] is None
    assert recipes.verify_blender() == []
