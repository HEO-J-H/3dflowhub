import notify


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []
    monkeypatch.setattr(notify, "call", lambda method, **p: sent.append((method, p)) or {"message_id": 7})
    return sent


def test_pr_button_records_decision_only_from_my_chat(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    import agents
    rec = []
    monkeypatch.setattr(agents, "record_decision", lambda site, n, v, note="": rec.append((site, n, v)))
    cb = {"callback_query": {"id": "c", "data": "pr:pix2poly:3:approve", "message": {"chat": {"id": 42}, "message_id": 1}}}
    assert "PR #3" in notify.handle_update(cb, {}) and rec == [("pix2poly", 3, "approve")]
    other = {"callback_query": {"id": "c", "data": "pr:pix2poly:3:reject", "message": {"chat": {"id": 999}}}}
    assert notify.handle_update(other, {}) == "" and len(rec) == 1  # 다른 대화방은 무시


def test_revise_waits_for_reply_then_records(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path)
    import agents
    rec = []
    monkeypatch.setattr(agents, "record_decision", lambda site, n, v, note="": rec.append((n, v, note)))
    state = {}
    cb = {"callback_query": {"id": "c", "data": "pr:pix2poly:3:revise", "message": {"chat": {"id": 42}, "message_id": 1}}}
    notify.handle_update(cb, state)
    assert rec == [] and "7" in state["awaiting"]  # 아직 기록 안 함, 답장 대기
    reply = {"message": {"chat": {"id": 42}, "text": "실제 엔진 호출까지", "reply_to_message": {"message_id": 7}}}
    assert "수정 요청" in notify.handle_update(reply, state)
    assert rec == [(3, "revise", "실제 엔진 호출까지")]


def test_proposal_button(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    import manager
    got = []
    monkeypatch.setattr(manager, "decide", lambda pid, v, note="": got.append((pid, v)))
    cb = {"callback_query": {"id": "c", "data": "prop:p-0123456789:accepted", "message": {"chat": {"id": 42}}}}
    notify.handle_update(cb, {})
    assert got == [("p-0123456789", "accepted")]


def test_new_only_once():
    st = {}
    assert notify._new(st, "pr:x:1") and not notify._new(st, "pr:x:1")


def test_disabled_without_secrets(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert "skipped" in notify.run()
