import build_site
import visuals


def test_youtube_post_gets_thumbnail():
    img, vid = visuals.post_image({"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    assert img == "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg" and vid


def test_shots_html_renders_three_values():
    h = build_site.shots_html([{"option": "Width", "items": [{"src": f"m/0-{i}.jpg", "label": f"W {i}"} for i in range(3)]}], "../../")
    assert h.count("<img") == 3 and "../../manual/m/0-1.jpg" in h
    assert build_site.shots_html([], "") == "" and build_site.videos_html(None) == ""
