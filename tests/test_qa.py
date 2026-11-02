import qa


def test_mechanical_flags_real_problems_only():
    ok = {"kind": "guide", "x": {"title": "t", "summary": "Houdini 의 Null 노드와 Nanite 를 씁니다. 충분한 한국어 설명입니다.",
                                 "steps": ["a", "b", "c"], "videos": [{"id": "x"}]}}
    assert qa.mechanical(ok) == []
    bad = {"kind": "guide", "x": {"title": "t", "summary": "TODO 여기에 설명 {{name}}", "steps": ["a"]}}
    p = qa.mechanical(bad)
    assert "자리표시 문구 남음" in p and "그림·영상 없음" in p and "따라 하기 단계가 너무 적음" in p
