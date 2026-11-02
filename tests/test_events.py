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


def test_deadline_in_reads_close_sentence():
    assert events.deadline_in("Entry closes on Monday, 22:30 GMT ( Mon, Nov 2, 2026 10:30 PM )") == "2026-11-02"
    assert events.deadline_in("Submissions open: October 15, 2026 Submissions close: October 31, 2026") == "2026-10-31"
    assert events.deadline_in("Posted on October 3, 2026") == ""


def test_conference_date_must_be_quoted_from_page(tmp_path, monkeypatch):
    import core
    import refs
    monkeypatch.setattr(events, "DIR", tmp_path)
    monkeypatch.setattr(events, "CONFERENCES", [("Test Conf", "https://example.org/", "해외")])
    page = "Welcome! Test Conf 2999 takes place October 21 - 23, 2999 in Amsterdam. " * 10
    monkeypatch.setattr(refs, "page_text", lambda *a, **k: page)
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"start": "2999-10-21", "end": "2999-10-23", "city": "Amsterdam", '
                                                     '"quote": "takes place October 21 - 23, 2999"}')
    got = events.conferences()
    assert got and got[0]["start"] == "2999-10-21"
    for f in tmp_path.glob("*.json"):
        f.unlink()
    monkeypatch.setattr(core, "llm", lambda *a, **k: '{"start": "2999-05-01", "end": "2999-05-02", "quote": "made up dates"}')
    assert events.conferences() == []  # 본문에 없는 인용 → 버림
