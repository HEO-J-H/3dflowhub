import json

import core
import showcase


def test_collect_auto_keeps_only_noted_items(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase, "AUTO_PATH", tmp_path / "auto.json")
    a = {"id": "sf-1", "kind": "sketchfab", "title": "Robot", "artist": "Kim", "artist_url": "", "url": "u",
         "embed": "https://sketchfab.com/models/1/embed", "thumb": "", "info": "hard surface"}
    b = {**a, "id": "yt-2", "kind": "youtube", "artist": ""}  # 작가 이름 없으면 제외
    c = {**a, "id": "sf-3"}  # 해설 없으면 제외
    monkeypatch.setattr(showcase, "_sketchfab", lambda: [a, c])
    monkeypatch.setattr(showcase, "_youtube", lambda week: [b])
    monkeypatch.setattr(core, "llm", lambda *x, **k: json.dumps({"notes": {"sf-1": "베벨 처리를 보세요", "yt-2": "x"}}))
    assert showcase.collect_auto() == 1
    items = showcase.auto_items()
    assert [i["id"] for i in items] == ["sf-1"] and items[0]["note"] == "베벨 처리를 보세요"
    assert showcase.collect_auto() == 0  # 이미 있는 작품은 다시 넣지 않음


def test_showcase_page_noindex_until_enough(tmp_path, monkeypatch):
    import build_site
    monkeypatch.setattr(showcase, "AUTO_PATH", tmp_path / "auto.json")
    monkeypatch.setattr(showcase, "PATH", tmp_path / "sc.json")
    monkeypatch.setattr(build_site, "OUT", tmp_path)
    build_site.build_showcase()
    assert "noindex" in (tmp_path / "showcase" / "index.html").read_text(encoding="utf-8")
    item = {"id": "sf-x", "kind": "sketchfab", "title": "T", "artist": "A", "artist_url": "", "url": "https://s/x",
            "embed": "https://sketchfab.com/models/x/embed", "thumb": "", "note": "볼 포인트"}
    core._save_json(showcase.AUTO_PATH, {"items": [{**item, "id": f"sf-{n}"} for n in range(showcase.INDEX_MIN)]})
    build_site.build_showcase()
    html = (tmp_path / "showcase" / "index.html").read_text(encoding="utf-8")
    assert "noindex" not in html and "data-embed=" in html and "<iframe" not in html.split("<script>")[0]
