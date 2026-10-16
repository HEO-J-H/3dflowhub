"""모든 테스트를 실제 데이터(memory/, content/, drafts/)와 격리.
에이전트가 새 테스트를 추가해도 실운영 기록(카테고리 사용 횟수 등)을 오염시키지 않도록 자동 적용된다."""
import pytest

import core


@pytest.fixture(autouse=True)
def _isolate_data(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MEMORY_PATH", tmp_path / "memory.json")
    monkeypatch.setattr(core, "STRATEGY_PATH", tmp_path / "strategy.json")
    monkeypatch.setattr(core, "PUBLISHED_LOG", tmp_path / "published.json")
    monkeypatch.setattr(core, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(core, "POSTS_DIR", tmp_path / "posts")
    monkeypatch.setattr(core, "DRAFT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(core, "NOTION_TOKEN", "")  # 테스트에서 노션 호출 금지
