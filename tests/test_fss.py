import fss


def test_detect_prefers_working_service(monkeypatch):
    monkeypatch.setattr(fss, "_finlife", lambda k: ("invalid", "010"))
    monkeypatch.setattr(fss, "_opendart", lambda k: ("ok", "000 정상"))
    r = fss.detect("abcd")
    assert r["service"] == "opendart" and r["key_len"] == 4 and "abcd" not in str(r)  # 키 값은 남기지 않음


def test_no_key(monkeypatch):
    monkeypatch.delenv("FSS_API_KEY", raising=False)
    assert fss.detect()["service"] is None


def test_fisis_detected(monkeypatch):
    monkeypatch.setattr(fss, "_finlife", lambda k: ("invalid", "010"))
    monkeypatch.setattr(fss, "_fisis", lambda k: ("ok", "000"))
    monkeypatch.setattr(fss, "_opendart", lambda k: ("invalid", "010"))
    assert fss.detect("x" * 32)["service"] == "fisis"
