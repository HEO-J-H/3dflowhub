import json

import compare
import core


def test_make_rejects_thin_and_keeps_good(monkeypatch):
    good = {"summary": "요약", "rows": [{"tool": t, "where": "X"} for t in ("Blender", "Maya", "3ds Max")],
            "pick": [{"case": "게임", "tool": "Blender", "why": "무료"}], "handoff": ["축"], "apply": ["a"], "pitfalls": ["b"]}
    monkeypatch.setattr(core, "llm", lambda *a, **k: json.dumps(good, ensure_ascii=False))
    x = compare.make(*compare.TOPICS[0])
    assert x and x["id"] == compare.TOPICS[0][0] and len(x["rows"]) == 3
    monkeypatch.setattr(core, "llm", lambda *a, **k: json.dumps({"summary": "s", "rows": [{"tool": "Blender", "where": "X"}]}))
    assert compare.make(*compare.TOPICS[0]) is None


def test_topic_slugs_unique():
    assert len({t[0] for t in compare.TOPICS}) == len(compare.TOPICS)
