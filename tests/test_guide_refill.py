import json

import core
import guides


def test_refill_topics_adds_new_and_skips_known(tmp_path, monkeypatch):
    sp = tmp_path / "strategy.json"
    monkeypatch.setattr(core, "STRATEGY_PATH", sp)
    monkeypatch.setattr(guides, "pending", lambda: [])
    monkeypatch.setattr(guides, "load_all", lambda: [])
    monkeypatch.setattr(guides, "CATALOG", [("Blender", "모디파이어", "Bevel modifier", "Bevel", None)])
    reply = {"topics": [{"group": "모디파이어", "name": "Bevel modifier", "title_ko": "중복"},
                        {"group": "모디파이어", "name": "Screw modifier", "title_ko": "Screw — 회전 복제"}]}
    monkeypatch.setattr(core, "llm", lambda *a, **k: json.dumps(reply))
    assert guides.refill_topics() == 1
    st = json.loads(sp.read_text(encoding="utf-8"))
    assert st["guide_topics"] == [["Blender", "모디파이어", "Screw modifier", "Screw — 회전 복제", None]]
    assert guides.refill_topics() == 0  # 하루 한 번만
