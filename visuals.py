"""참고 페이지에 '볼 것' 붙이기 — 글보다 그림·영상 (아티스트는 눈으로 고른다).

심화 매뉴얼: 원래 가이드의 영상·메뉴 경로 + 공식 문서 그림(재사용 허용 문서만) (+ Blender 값 비교 렌더는 manual_shots)
툴 비교: 툴마다 그 작업을 하는 튜토리얼 영상 1개
오류 해결: 그 오류를 고치는 영상 2개
버전별 바뀐 점: 공식 발표 페이지 대표 이미지(og:image) + 새 기능 소개 영상 2개
한 번 붙인 항목엔 visuals_at 표시 → 다시 하지 않음. evolve 가 주기적으로 조금씩 (새 페이지도 자동으로).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

import core


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def og_image(url: str) -> str:
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (3dflowhub)"}, timeout=15).text[:200000]
    except requests.RequestException:
        return ""
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
    return m.group(1) if m and m.group(1).startswith("http") else ""


def for_manual(x: dict) -> dict:
    import guides
    g = next((g for g in guides.load_all() if g["id"] == x["id"]), {})
    x["videos"] = g.get("videos") or guides.find_videos(f"{x['tool']} {x['name']} tutorial")
    x["menu_path"] = g.get("menu_path") or []
    x["images"] = guides.doc_images(x.get("doc"), n=6) if x.get("doc") else []
    return x


def for_compare(x: dict) -> dict:
    import guides
    short = x.get("task", x["title"]).split(":")[0][:60]
    for r in x["rows"]:
        if "video" not in r:
            v = guides.find_videos(f"{r['tool']} {short} tutorial", n=1)
            r["video"] = v[0] if v else None
    return x


def for_fix(x: dict) -> dict:
    import guides
    err = re.sub(r"[\"'`]", "", x.get("error", ""))[:70]
    x["videos"] = guides.find_videos(f"{x['tool']} {err} fix", n=2) or guides.find_videos(f"{x['tool']} {x['title'][:40]}", n=1)
    return x


def for_change(x: dict) -> dict:
    import guides
    src = x.get("source") or x.get("url") or ""
    x["hero"] = og_image(src) if src else ""
    x["videos"] = guides.find_videos(f"{x['tool']} {x.get('version', '')} new features", n=2)
    return x


def for_recipe(x: dict) -> dict:
    import guides
    x["videos"] = guides.find_videos(f"{x['host']} {x['title'][:50]}", n=1) or guides.find_videos(f"{x['host']} {x.get('category', '')} tutorial", n=1)
    return x


# ── 소식 글: 그림이 없는 글(현재 약 65%)에 출처별로 그림 찾기 ──
def post_image(p: dict) -> tuple[str, str]:
    """(그림 주소, 영상 주소) — 유튜브 썸네일, arXiv 논문 그림, reddit 미리보기, 원문 og:image, 마지막으로 관련 영상."""
    import html as _html
    from urllib.parse import urljoin
    url = p.get("url", "")
    if (m := re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})", url)):
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg", url
    if (m := re.search(r"arxiv\.org/(?:abs|pdf|html)/([\d.]+(?:v\d+)?)", url)):
        base = f"https://arxiv.org/html/{m.group(1)}/"
        try:
            t = requests.get(base, headers={"User-Agent": "Mozilla/5.0 (3dflowhub)"}, timeout=20).text
            if (im := re.search(r'<img[^>]+src="([^"]+\.(?:png|jpg|jpeg|gif))"', t, re.I)):
                return urljoin(base, im.group(1)), ""
        except requests.RequestException:
            pass
    if "reddit.com" in url:
        try:
            j = requests.get(url.rstrip("/") + ".json", headers={"User-Agent": "3dflowhub/1.0"}, timeout=15).json()
            d = j[0]["data"]["children"][0]["data"]
            src = (((d.get("preview") or {}).get("images") or [{}])[0].get("source") or {}).get("url", "")
            if src:
                return _html.unescape(src), ""
        except Exception:  # noqa: BLE001
            pass
    if "news.google.com" not in url:
        if (img := og_image(url)):
            return img, ""
    import guides
    v = guides.find_videos(p.get("title") or p.get("title_ko", ""), n=1)  # 원문 그림이 없으면 같은 주제 영상
    if v:
        return f"https://i.ytimg.com/vi/{v[0]['id']}/hqdefault.jpg", f"https://www.youtube.com/watch?v={v[0]['id']}"
    return "", ""


def backfill_posts(limit: int = 30) -> int:
    n = 0
    for f in sorted(core.POSTS_DIR.glob("*.json"), reverse=True):
        if n >= limit:
            break
        p = core._load_json(f, {})
        m = p.get("media") or {}
        if m.get("image") or m.get("video") or p.get("img_tried"):
            continue
        try:
            img, vid = post_image(p)
        except Exception:  # noqa: BLE001
            img, vid = "", ""
        p["media"] = {**m, "image": img or m.get("image", ""), "video": vid or m.get("video", "")}
        p["img_tried"] = True
        core._save_json(f, p)
        n += 1
    return n


def backfill(limit: int = 12) -> list[str]:
    """그림·영상이 아직 없는 페이지에 붙임 (한 번에 limit 개)."""
    import compare
    import manual
    import recipes
    import refs
    jobs = [(x, for_manual, manual.DIR) for x in manual.load_all()] + \
           [(x, for_compare, compare.DIR) for x in compare.load_all()] + \
           [(x, for_fix, refs.FIX_DIR) for x in refs.load("fix")] + \
           [(x, for_change, refs.CHANGE_DIR) for x in refs.load("change")] + \
           [(x, for_recipe, recipes.RECIPE_DIR) for x in recipes.load_all()]
    done = []
    for x, fn, d in [j for j in jobs if not j[0].get("visuals_at")][:limit]:
        try:
            x = fn(x)
        except Exception as e:  # noqa: BLE001 — 그림이 없어도 페이지는 그대로
            core.log.warning("그림·영상 붙이기 실패 %s: %s", x.get("id"), e)
        x["visuals_at"] = _now()
        core._save_json(d / f"{x['id']}.json", x)
        done.append(x["id"])
    return done


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    print(len(backfill(n)), backfill_posts(int(sys.argv[2]) if len(sys.argv) > 2 else 30))
