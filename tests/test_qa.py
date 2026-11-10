import qa


def test_mechanical_flags_real_problems_only():
    ok = {"kind": "guide", "x": {"title": "t", "summary": "Houdini 의 Null 노드와 Nanite 를 씁니다. 충분한 한국어 설명입니다.",
                                 "steps": ["a", "b", "c"], "videos": [{"id": "x"}]}}
    assert qa.mechanical(ok) == []
    bad = {"kind": "guide", "x": {"title": "t", "summary": "TODO 여기에 설명 {{name}}", "steps": ["a"]}}
    p = qa.mechanical(bad)
    assert "자리표시 문구 남음" in p and "그림·영상 없음" in p and "따라 하기 단계가 너무 적음" in p


def test_feedback_targets_marks_downvoted_guide(tmp_path, monkeypatch):
    import core
    import guides
    import qa
    monkeypatch.setattr(guides, "GUIDE_DIR", tmp_path)
    core._save_json(tmp_path / "g1.json", {"id": "g1", "title": "t"})
    monkeypatch.setattr(core, "ROOT", tmp_path)
    (tmp_path / "memory").mkdir()
    core._save_json(tmp_path / "memory" / "feedback.json", {"pages": {
        "/3dflowhub/learn/g1/": {"up": 0, "down": 3}, "/3dflowhub/learn/g2/": {"up": 5, "down": 2}}})
    assert qa.feedback_targets() == ["/3dflowhub/learn/g1/"]
    assert core._load_json(tmp_path / "g1.json", {})["qa_redo"] is True
    assert qa.feedback_targets() == []  # 같은 👎 수로는 한 번만
