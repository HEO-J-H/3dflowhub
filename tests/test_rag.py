import rag


def test_tokens_korean_bigrams():
    assert rag.tokens("모서리 Bevel") == ["모서", "서리", "bevel"]


def test_search_ranks_relevant_first():
    ix = rag.Index([{"id": "a", "kind": "guide", "title": "Bevel 모서리 다듬기", "text": "edge bevel"},
                    {"id": "b", "kind": "post", "title": "렌더링 소식", "text": "render news"}])
    hits = ix.search("모서리 bevel", k=2)
    assert hits and hits[0]["id"] == "a"
    assert ix.search("모서리 bevel", exclude={"a"}) == []
