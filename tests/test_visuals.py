import build_site
import visuals


def test_youtube_post_gets_thumbnail():
    img, vid = visuals.post_image({"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    assert img == "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg" and vid


def test_shots_html_renders_three_values():
    h = build_site.shots_html([{"option": "Width", "items": [{"src": f"m/0-{i}.jpg", "label": f"W {i}"} for i in range(3)]}], "../../")
    assert h.count("<img") == 3 and "../../manual/m/0-1.jpg" in h
    assert build_site.shots_html([], "") == "" and build_site.videos_html(None) == ""


def test_visibly_different_rejects_near_identical(tmp_path):
    from PIL import Image, ImageDraw
    import manual_shots

    def img(name, box):
        im = Image.new("L", (480, 300), 120)
        if box:
            ImageDraw.Draw(im).rectangle(box, fill=230)
        im.save(tmp_path / name)
        return tmp_path / name
    a, b, c = img("a.jpg", (100, 80, 200, 200)), img("b.jpg", (260, 80, 360, 200)), img("c.jpg", (100, 80, 201, 200))
    assert manual_shots.visibly_different([a, b, img("d.jpg", None)])
    assert not manual_shots.visibly_different([a, b, c])  # a 와 c 는 1px 차이 → 같은 그림


def test_arxiv_image_url_has_number_once(monkeypatch):
    import visuals

    class R:
        text = '<img src="2611.11602v1/figures/a.png">'
    monkeypatch.setattr(visuals.requests, "get", lambda *a, **k: R())
    img, _ = visuals.post_image({"url": "https://arxiv.org/abs/2611.11602v1"})
    assert img == "https://arxiv.org/html/2611.11602v1/figures/a.png"
