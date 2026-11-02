import rag


def test_tokens_korean_bigrams():
    assert rag.tokens("모서리 Bevel") == ["모서", "서리", "bevel"]


def test_search_ranks_relevant_first():
    ix = rag.Index([{"id": "a", "kind": "guide", "title": "Bevel 모서리 다듬기", "text": "edge bevel"},
                    {"id": "b", "kind": "post", "title": "렌더링 소식", "text": "render news"}])
    hits = ix.search("모서리 bevel", k=2)
    assert hits and hits[0]["id"] == "a"
    assert ix.search("모서리 bevel", exclude={"a"}) == []


def test_same_story_by_content(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    import core
    monkeypatch.setattr(core, "POSTS_DIR", tmp_path)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (tmp_path / f"{day}-a.json").write_text(json.dumps(
        {"title_ko": "블렌더 4.5 출시, 바이킹 렌더러 속도 개선", "summary": "블렌더 4.5 버전이 출시되며 렌더링 속도와 지오메트리 노드가 개선됐다"},
        ensure_ascii=False), encoding="utf-8")
    assert core.same_story_saved("블렌더 4.5 정식 출시 — 렌더러 속도 개선",
                                 summary="블렌더 4.5 버전 출시로 렌더링 속도와 지오메트리 노드 개선")
    assert not core.same_story_saved("언리얼 엔진 5.6 나나이트 소식", summary="언리얼 엔진 나나이트 폴리지 기능이 추가됐다")
