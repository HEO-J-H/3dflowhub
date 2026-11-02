import events


def test_load_all_hides_past(tmp_path, monkeypatch):
    import core
    monkeypatch.setattr(events, "DIR", tmp_path)
    core._save_json(tmp_path / "a.json", {"id": "a", "deadline": "2000-01-01", "title": "old"})
    core._save_json(tmp_path / "b.json", {"id": "b", "deadline": "2999-01-01", "title": "new"})
    assert [x["id"] for x in events.load_all()] == ["b"]


def test_relevant_titles_only():
    assert events.RELEVANT.search("제1회 게임 시나리오·그래픽 공모전")
    assert not events.RELEVANT.search("부안 지방정원 가을 사진 공모전")
