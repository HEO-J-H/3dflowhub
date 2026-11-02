import build_site
import seo_audit


def test_subpage_description_is_unique():
    html = build_site.page("Blender Bevel 가이드 - 3dflowhub", "<h1>x</h1>", "../")
    assert 'content="Blender Bevel 가이드 — ' in html
    home = build_site.page(build_site.SITE_TITLE, "<h1>x</h1>", "")
    assert f'content="{build_site.SITE_DESC[:150]}"' in home


def test_guide_h1_has_tool():
    assert build_site.guide_h1({"title": "Boolean — 합치기", "tool": "Houdini"}) == "Houdini Boolean — 합치기"
    assert build_site.guide_h1({"title": "Blender 지오메트리 노드", "tool": "Blender"}) == "Blender 지오메트리 노드"


def test_audit_finds_duplicates_and_orphans(tmp_path, monkeypatch):
    def write(rel, title, h1, links=""):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'<title>{title}</title><meta name="description" content="{title}"><h1>{h1}</h1>{links}', encoding="utf-8")
    write("index.html", "홈", "홈", '<a href="a/">a</a>')
    write("a/index.html", "같은 제목", "A")
    write("b/index.html", "같은 제목", "B")      # 홈에서 링크 없음 → 고아, 제목 중복
    (tmp_path / "sitemap.xml").write_text(f"<loc>{seo_audit.BASE}</loc><loc>{seo_audit.BASE}a/</loc>", encoding="utf-8")
    r = seo_audit.audit(tmp_path)
    assert r["dup_title_count"] == 2 and r["orphan_count"] == 1 and r["not_in_sitemap_count"] == 1
