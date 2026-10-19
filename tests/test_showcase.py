import pytest

import showcase


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(showcase, "PATH", tmp_path / "showcase.json")


def test_flow_requires_consent_before_publish():
    iid = showcase.add("Kim", "Robot", "https://www.artstation.com/artwork/abc")
    assert iid and showcase.add("Kim", "Robot", "https://www.artstation.com/artwork/abc") == ""  # 중복
    assert showcase.published() == []
    with pytest.raises(ValueError):
        showcase.set_status(iid, "approved", "")  # 허락 기록 없이는 게시 불가
    showcase.set_status(iid, "approved", "10/20 ArtStation 메시지로 동의")
    assert [i["id"] for i in showcase.published()] == [iid]
    showcase.set_status(iid, "declined")
    assert showcase.published() == []


def test_request_message_has_link_and_opt_out():
    it = {"artist": "Kim", "title": "Robot", "url": "https://x"}
    assert "https://x" in showcase.request_message(it) and "거절" in showcase.request_message(it)
    assert "no problem" in showcase.request_message(it, "en")
