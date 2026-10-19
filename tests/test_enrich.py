import enrich


def test_unsupported_numbers_catches_changed_figure():
    src = "300억 파라미터 규모의 Nemotron 3 LTM, 2026년, 가격 1,299달러"
    assert enrich.unsupported_numbers("30억 파라미터 모델 [1]", src) == ["30억"]
    assert enrich.unsupported_numbers("30억 파라미터", src + " 댓글 30") == ["30억"]  # 다른 곳의 30 은 근거가 아님
    assert enrich.unsupported_numbers("300억 파라미터, 1299달러, 2026년, 3단계 [2]", src) == []


def test_relevance_needs_two_keywords():
    r = {"title": "UnrealizeX add-on: free mesh reconstruction", "excerpt": "for Blender users"}
    assert enrich.relevant(r, "Blender UnrealizeX")
    assert not enrich.relevant(r, "Unity")  # 단어 하나짜리 검색은 너무 넓음
    assert not enrich.relevant({"title": "Cycles updates", "excerpt": ""}, "Blender UnrealizeX")


def test_query_uses_english_tags_without_duplicates():
    p = {"title": "", "category": "Unreal Engine", "tags": ["Unreal Engine", "LEGO Batman", "게임개발"]}
    assert enrich.query_for(p) == "Unreal Engine LEGO Batman"


def test_weak_and_already_enriched():
    short = {"summary": "a" * 100, "sections": [{"body": "b" * 500}]}
    assert enrich.is_weak(short)
    assert not enrich.is_weak({**short, "enriched_at": "skip"})
    assert not enrich.is_weak({"summary": "", "sections": [{"body": "c" * 1300}]})
