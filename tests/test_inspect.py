import inspect_site


def test_inspector_catches_owner_reported_bug_types(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "a.html").write_text(
        "<h1>제목</h1><li>{'step': 1, 'description': 'x'}</li><p>None</p>"
        '<img src="https://arxiv.org/html/2611.1v1/2611.1v1/a.png">', encoding="utf-8")
    (tmp_path / "p" / "b.html").write_text("<h1>제목</h1><p>검증된 스크립트 받아보기</p>", encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<loc>https://x/c/3d-생성-ai/</loc>", encoding="utf-8")
    r = inspect_site.inspect(tmp_path)["issues"]
    for k in ("날것 데이터가 화면에", "None/undefined 표시", "논문 그림 주소 번호 중복", "그만둔 메뉴 이름",
              "사이트맵 주소에 한글 그대로", "같은 제목 글 여러 개"):
        assert k in r, k


def test_inspector_passes_clean_page(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "a.html").write_text("<h1>Blender 5.0</h1><p>정상 글</p>", encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<loc>https://x/c/3d-%EC%83%9D/</loc>", encoding="utf-8")
    assert inspect_site.inspect(tmp_path)["issues"] == {}


def test_qa_flags_raw_struct():
    import qa
    p = qa.mechanical({"kind": "post", "x": {"summary": "한국어 설명이 충분히 들어 있는 글입니다 " * 3,
                                             "try_it": ["{'step': 1, 'description': 'a'}"], "media": {"image": "x"}}})
    assert "날것 데이터가 글에" in p


def test_radar_filters():
    import radar
    assert radar.KAGGLE_OK.search("modelnet40 - princeton 3d object dataset")
    assert radar.KAGGLE_NO.search("3d liver segmentation") and radar.KAGGLE_NO.search("rsna trained 3d model weights")
    assert radar._lic("mit")["commercial"] == "가능" and radar._lic("cc-by-nc-4.0")["commercial"] == "불가"
