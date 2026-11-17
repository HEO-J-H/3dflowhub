from datetime import datetime, timezone

import core
import weekly_mail as wm

MON_9KST = datetime(2026, 11, 16, 0, 30, tzinfo=timezone.utc)   # 월요일 09:30 KST
SUN_KST = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)     # 일요일


def test_last_week_and_due():
    start, end, week = wm.last_week(MON_9KST)
    assert week == "2026-W46" and start.day == 9 and end.day == 16
    assert wm.due(MON_9KST, {}) and not wm.due(SUN_KST, {})
    assert not wm.due(MON_9KST, {"weekly_mail_week": "2026-W46"})  # 한 주에 한 번만


def test_no_key_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "STRATEGY_PATH", tmp_path / "s.json")
    monkeypatch.delenv("BUTTONDOWN_API_KEY", raising=False)
    assert "없음" in wm.run(MON_9KST)


def test_send_records_week_and_failure_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "STRATEGY_PATH", tmp_path / "s.json")
    monkeypatch.setenv("BUTTONDOWN_API_KEY", "k")
    monkeypatch.setattr(wm, "compose", lambda now=None: {"subject": "S", "body": "B", "week": "2026-W46"})
    import requests

    class R:
        def __init__(self, ok): self.ok, self.status_code, self.text = ok, 200 if ok else 500, ""
    sent = []
    monkeypatch.setattr(requests, "post", lambda url, **k: (sent.append(k["json"]), R(False))[1])
    assert "실패" in wm.run(MON_9KST)
    assert core.load_strategy().get("weekly_mail_week") is None  # 실패하면 다음 실행에서 다시
    monkeypatch.setattr(requests, "post", lambda url, **k: (sent.append(k["json"]), R(True))[1])
    assert "완료" in wm.run(MON_9KST)
    assert core.load_strategy()["weekly_mail_week"] == "2026-W46"
    assert wm.run(MON_9KST) == "발송 시각 아님" and len(sent) == 2
