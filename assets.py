"""무료 에셋 모음 — 새로 올라온 무료 텍스처·재질·HDRI·3D 모델을 출처별로 모아 /assets/ 페이지로.

AI 를 쓰지 않음(요약할 글이 아니라 '목록'이 가치). 모두 상업적 사용 가능한 무료 라이선스 출처만:
- Poly Haven (CC0, 공개 API) — 텍스처·HDRI·모델
- ambientCG (CC0, 공개 API) — 재질·HDRI
- 3DTextures.me · ShareTextures (무료 PBR, 피드) — 각 사이트 라이선스 표기
이미지는 각 출처의 썸네일 주소를 그대로 링크(파일을 복사해 오지 않음), 받기는 원래 사이트에서.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

import core

PATH = core.ROOT / "content" / "assets.json"
UA = {"User-Agent": "3dflowhub asset digest (+https://heo-j-h.github.io/3dflowhub/)"}
KEEP = 400
TYPE_KO = {"texture": "텍스처·재질", "hdri": "HDRI", "model": "3D 모델"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url: str):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def from_polyhaven(per_type: int = 24) -> list[dict]:
    out = []
    for t, kind in (("textures", "texture"), ("hdris", "hdri"), ("models", "model")):
        d = _get(f"https://api.polyhaven.com/assets?t={t}") or {}
        newest = sorted(d.items(), key=lambda kv: -int(kv[1].get("date_published", 0)))[:per_type]
        for k, v in newest:
            out.append({"id": f"ph-{k}", "source": "Poly Haven", "license": "CC0", "type": kind,
                        "title": v.get("name", k), "url": f"https://polyhaven.com/a/{k}",
                        "image": f"https://cdn.polyhaven.com/asset_img/thumbs/{k}.png?width=256&height=256",
                        "tags": (v.get("categories") or [])[:4],
                        "date": datetime.fromtimestamp(int(v.get("date_published", 0)), timezone.utc).date().isoformat()})
    return out


def from_ambientcg(limit: int = 40) -> list[dict]:
    d = _get(f"https://ambientcg.com/api/v2/full_json?limit={limit}&sort=Latest&include=imageData") or {}
    out = []
    for a in d.get("foundAssets") or []:
        dt = str(a.get("dataType", ""))
        kind = "hdri" if dt == "HDRI" else "model" if dt in ("3DModel", "3D Model") else "texture"
        img = (a.get("previewImage") or {}).get("256-PNG") or (a.get("previewImage") or {}).get("128-PNG") or ""
        out.append({"id": f"acg-{a.get('assetId')}", "source": "ambientCG", "license": "CC0", "type": kind,
                    "title": a.get("displayName") or a.get("assetId"), "url": a.get("shortLink") or "",
                    "image": img, "tags": [], "date": str(a.get("releaseDate", ""))[:10]})
    return out


def from_feed(url: str, source: str, license_: str) -> list[dict]:
    try:
        feed = core.fetch_feed(url)
    except Exception:
        return []
    out = []
    for e in feed.entries[:20]:
        img = core.rss_image(e)
        if not img:
            m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)', str(e.get("content", "")))
            img = m.group(1) if m else ""
        t = e.get("published_parsed") or e.get("updated_parsed")
        out.append({"id": f"{source[:3].lower()}-{core.url_hash(e.get('link', ''))}", "source": source,
                    "license": license_, "type": "texture", "title": e.get("title", "").strip(),
                    "url": e.get("link", ""), "image": img, "tags": [],
                    "date": f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}" if t else ""})
    return out


def og_image(url: str) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        head = r.text[:200000]
        m = re.search(r"""<meta[^>]+property=["']og:image["'][^>]+content=["'](https?://[^"']+)""", head) \
            or re.search(r"""<meta[^>]+content=["'](https?://[^"']+)["'][^>]+property=["']og:image""", head)
        return m.group(1) if m else ""
    except requests.RequestException:
        return ""


def collect() -> int:
    """출처에서 새 에셋을 받아 합침. 새로 생긴 개수 반환 (실패한 출처는 건너뜀)."""
    have = {x["id"]: x for x in core._load_json(PATH, [])}
    items = (from_polyhaven() + from_ambientcg()
             + from_feed("https://3dtextures.me/feed/", "3DTextures.me", "무료 (사이트 라이선스)")
             + from_feed("https://www.sharetextures.com/feed", "ShareTextures", "CC0"))
    new = 0
    for x in items:  # 피드에 미리보기가 없으면 원래 페이지의 대표 이미지(og:image)를 한 번만 가져와 저장
        if not x.get("image") and x["id"] not in have and x.get("url"):
            x["image"] = og_image(x["url"])
        if x.get("url") and x.get("title") and x["id"] not in have:
            have[x["id"]] = {**x, "seen": _now()}
            new += 1
    data = sorted(have.values(), key=lambda x: (x.get("date") or "", x.get("seen", "")), reverse=True)[:KEEP]
    core._save_json(PATH, data)
    return new


def load() -> list[dict]:
    return core._load_json(PATH, [])


if __name__ == "__main__":
    print(collect())
