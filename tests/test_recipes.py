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
    bad = recipes.check_script("maxscript", "3ds Max", ok + "(")
    assert "괄호" in bad or "문법" in bad  # 문법 분석기가 있으면 먼저 잡음
    assert "외부" in recipes.check_script("maxscript", "3ds Max", ok + 'DOSCommand "x"')


def test_blender_recipe_published_only_after_runtime_ok():
    assert not recipes.published({"host": "Blender"})
    assert recipes.published({"host": "Blender", "runtime": {"ok": True}})
    assert recipes.published({"host": "3ds Max"})


def test_no_blender_means_no_verdict(monkeypatch):
    monkeypatch.setattr(recipes, "blender_bin", lambda: None)
    assert recipes.run_blender_check("x")["ok"] is None
    assert recipes.verify_blender() == []


import shutil

import pytest


@pytest.mark.skipif(not shutil.which("node") or not recipes.MXS_CHECKER.exists(), reason="node·MAXScript 분석기 없음")
def test_maxscript_parser_catches_grammar_error():
    good = 'fn cleanUp objs = (\n  for o in objs do (print o.name)\n)\n' * 3
    assert recipes.maxscript_parse_errors(good) == ""
    assert "문법" in recipes.maxscript_parse_errors(good + "fn f a = (a + \nfor o in x do print o))\n")


def test_maya_unknown_command_and_flag():
    pytest.importorskip("mypy")
    code = ('import maya.cmds as cmds\ndef run():\n    for o in cmds.ls(selection=True):\n'
            '        cmds.makeIdentity(o, apply=True, scale=True)\n')
    assert recipes.maya_api_errors(code) == ""
    assert "polyCleanupNotReal" in recipes.maya_api_errors(code + "        cmds.polyCleanupNotReal(o)\n")
    assert "bogus" in recipes.maya_api_errors(code + "        cmds.polyMergeVertex(o, bogus=1)\n")


@pytest.mark.skipif(not shutil.which("node") or not recipes.MXS_CHECKER.exists(), reason="node·MAXScript 분석기 없음")
def test_maxscript_made_up_functions():
    code = ('fn cleanUp obj thr: = (\n  local n = polyop.getNumVerts obj\n  polyop.weldVertsByThreshold obj #all\n'
            '  for o in selection do print o.name\n  n\n)\nrollout r "x" (button btnGo "Go")\ncleanUp $\n')
    assert recipes.maxscript_parse_errors(code) == ""  # 실제 함수·직접 선언한 이름은 통과
    bad = recipes.maxscript_parse_errors(code + "makeAwesome $\npolyop.weldEverythingNow $\n")
    assert "makeAwesome" in bad and "polyop.weldEverythingNow" in bad
