import json

import core
import manual

G = {"id": "blender-bevel-x", "tool": "Blender", "name": "Bevel", "title": "Bevel — 모서리", "doc": "", "steps": [], "params": []}


def test_make_requires_depth(monkeypatch):
    deep = {"overview": "o", "options": [{"name": f"O{i}", "effect": "e"} for i in range(5)],
            "recipes": [{"title": "r", "steps": ["a", "b"]}], "troubleshoot": [{"symptom": "s", "fix": "f"}]}
    monkeypatch.setattr(core, "llm", lambda *a, **k: json.dumps(deep))
    x = manual.make(G)
    assert x and len(x["options"]) == 5 and x["recipes"][0]["steps"] == ["a", "b"]
    monkeypatch.setattr(core, "llm", lambda *a, **k: json.dumps({**deep, "options": deep["options"][:2]}))
    assert manual.make(G) is None


def test_official_doc_detection():
    assert manual._official("https://docs.blender.org/manual/en/latest/x.html")
    assert not manual._official("https://help.autodesk.com/view/3DSMAX/2026/ENU/?query=Edit")
