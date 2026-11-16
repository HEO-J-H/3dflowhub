"""
이번 주 작품 소개 — 커뮤니티 포트폴리오를 '작가 허락을 받은 것만' 소개한다
==========================================================================
흐름: 후보 등록(운영자) → 허락 요청 메시지 복사해 작가에게 개별 전송(사람) → 허락 받음 기록(허락 내용 메모 필수)
      → 사이트 /showcase/ 에 게시. 거절·철회 요청은 즉시 내림.
- 이메일 등 연락처는 저장하지 않는다 (작가 이름·작품 링크·허락 메모만)
- 이미지는 작가가 사용을 허락한 주소만 (없으면 링크 카드만)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import core

PATH = core.ROOT / "content" / "showcase.json"
STATUS = {"candidate": "후보", "asked": "허락 요청함", "approved": "게시 중", "declined": "거절·철회"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> list[dict]:
    return core._load_json(PATH, {"items": []}).get("items", [])


def save(items: list[dict]) -> None:
    core._save_json(PATH, {"note": "작가 허락을 받은 작품만 게시 (status=approved)", "items": items})


def add(artist: str, title: str, url: str, note: str = "", image: str = "") -> str:
    items = load()
    iid = hashlib.md5(url.strip().encode()).hexdigest()[:10]
    if any(i["id"] == iid for i in items):
        return ""
    items.append({"id": iid, "artist": artist.strip()[:60], "title": title.strip()[:80], "url": url.strip()[:300],
                  "image": image.strip()[:300], "note": note.strip()[:300], "status": "candidate", "at": _now()})
    save(items)
    return iid


def set_status(iid: str, status: str, consent: str = "") -> None:
    assert status in STATUS
    if status == "approved" and len(consent.strip()) < 5:
        raise ValueError("허락 받은 내용(언제·어디서·어떻게)을 적어야 게시할 수 있습니다")
    items = load()
    for i in items:
        if i["id"] == iid:
            i["status"] = status
            i[f"{status}_at"] = _now()
            if consent:
                i["consent"] = consent.strip()[:300]
    save(items)


def remove(iid: str) -> None:
    save([i for i in load() if i["id"] != iid])


def published() -> list[dict]:
    return sorted([i for i in load() if i.get("status") == "approved"], key=lambda i: i.get("approved_at", ""),
                  reverse=True)


def request_message(item: dict, lang: str = "ko") -> str:
    """작가에게 보낼 허락 요청문 (사람이 복사해 개별 전송). 대량 발송 금지."""
    site = "https://3dflowhub.kr/showcase/"
    if lang == "en":
        return (f"Hi {item['artist']},\n\nI run 3dflowhub, a small Korean site for 3D artists (DCC, game engines, VFX). "
                f"I really liked your work \"{item['title']}\" ({item['url']}) and would love to feature it in our "
                f"weekly showcase ({site}) with your name and a link back to your page.\n\n"
                "Would that be OK? If you'd prefer a specific image or credit text, just let me know. "
                "If not, no problem at all — thanks for sharing your work!\n")
    return (f"안녕하세요 {item['artist']}님,\n\n3D 작업자를 위한 소식·가이드 사이트 3dflowhub 를 운영하고 있습니다. "
            f"올려 주신 \"{item['title']}\" 작품({item['url']})이 인상 깊어서, 저희 '이번 주 작품' 코너({site})에 "
            "작가님 이름과 원본 링크를 함께 소개해도 될지 여쭙고 싶습니다.\n\n"
            "괜찮으시면 사용해도 되는 이미지나 원하시는 표기 방식을 알려 주세요. "
            "원치 않으시면 편하게 거절하셔도 됩니다. 좋은 작업 공유해 주셔서 감사합니다!\n")


# ─────────── 자동 소개: 작가가 '다른 사이트에 넣기'를 이미 허용한 작품만 (허락 요청 불필요) ───────────
# Sketchfab 스태프 픽(임베드 공개) · 유튜브 브레이크다운(퍼가기 허용, oEmbed 로 확인). 작가 이름·원본 링크 필수,
# 한국어 '볼 포인트' 해설을 붙여 공부 자료로. 그림을 내려받아 저장하지 않고 원래 서비스의 임베드·썸네일 주소만 씀.
AUTO_PATH = core.ROOT / "content" / "showcase_auto.json"
AUTO_KEEP = 30
INDEX_MIN = 6  # 이만큼 쌓이기 전에는 검색 제외 (빈·얇은 페이지 방지)
YT_QUERIES = ["3d environment breakdown", "character sculpt breakdown zbrush", "houdini fx breakdown",
              "unreal engine environment breakdown", "blender animation breakdown", "substance painter texturing breakdown"]


def auto_items() -> list[dict]:
    return core._load_json(AUTO_PATH, {"items": []}).get("items", [])


def _sketchfab(n: int = 6) -> list[dict]:
    import requests
    r = requests.get("https://api.sketchfab.com/v3/models", timeout=20,
                     params={"staffpicked": "true", "sort_by": "-publishedAt", "count": 24})
    r.raise_for_status()
    out = []
    for m in r.json().get("results", []):
        if m.get("isAgeRestricted") or not m.get("embedUrl") or not m.get("uid"):
            continue
        thumbs = sorted((t for t in (m.get("thumbnails") or {}).get("images", []) if t.get("width", 0) >= 400),
                        key=lambda t: t["width"])
        user = m.get("user") or {}
        out.append({"id": "sf-" + m["uid"], "kind": "sketchfab", "title": (m.get("name") or "")[:80],
                    "artist": (user.get("displayName") or user.get("username") or "")[:60],
                    "artist_url": user.get("profileUrl", ""), "url": f"https://sketchfab.com/3d-models/{m['uid']}",
                    "embed": m["embedUrl"], "thumb": thumbs[0]["url"] if thumbs else "",
                    "info": (m.get("description") or "")[:400]})
        if len(out) >= n:
            break
    return out


def _youtube(week: int) -> list[dict]:
    import guides
    out = []
    for q in (YT_QUERIES[week % len(YT_QUERIES)], YT_QUERIES[(week + 3) % len(YT_QUERIES)]):
        for v in guides.find_videos(q, n=1):
            out.append({"id": "yt-" + v["id"], "kind": "youtube", "title": v["title"][:80], "artist": v["author"][:60],
                        "artist_url": "", "url": f"https://www.youtube.com/watch?v={v['id']}",
                        "embed": f"https://www.youtube-nocookie.com/embed/{v['id']}",
                        "thumb": f"https://i.ytimg.com/vi/{v['id']}/hqdefault.jpg", "info": q})
    return out


def _notes(items: list[dict]) -> dict:
    """작품마다 '무엇을 눈여겨보면 배울 게 있나' 한국어 1~2문장 (AI 1회 호출)."""
    if not items:
        return {}
    lst = "\n".join(f'- {i["id"]} | {i["title"]} | {i["info"][:200]}' for i in items)
    prompt = ("For each 3D artwork below, write 1-2 Korean sentences telling a learner what to look at to learn from it "
              "(technique, workflow, topology, lighting, etc.). Only say what is plausible from the title/description; "
              "do not invent facts or praise. Return JSON {\"notes\": {\"<id>\": \"한국어 문장\"}}.\n" + lst)
    out = core._parse_json(core.llm(prompt, system="You are a senior 3D instructor. Output JSON only.",
                                    max_tokens=1200, json_mode=True)) or {}
    return {k: str(v).strip()[:220] for k, v in (out.get("notes") or {}).items() if str(v).strip()}


def collect_auto() -> int:
    """주 1회 호출(evolve). 새 작품 추가 수를 돌려준다."""
    have = auto_items()
    seen = {i["id"] for i in have}
    week = int(datetime.now(timezone.utc).strftime("%V"))
    new = []
    for fn in (lambda: _sketchfab(), lambda: _youtube(week)):
        try:
            new += [i for i in fn() if i["id"] not in seen]
        except Exception as e:
            core.log.info("작품 자동 소개 수집 일부 실패: %s", e)
    try:
        notes = _notes(new)
    except Exception as e:
        core.log.info("작품 해설 생성 실패: %s", e)
        return 0
    now = _now()
    new = [{**i, "note": notes[i["id"]], "at": now} for i in new if i["id"] in notes and i["artist"]]
    core._save_json(AUTO_PATH, {"note": "작가가 임베드·퍼가기를 허용한 작품만 자동 소개 (Sketchfab·YouTube)",
                                "items": (new + have)[:AUTO_KEEP]})
    return len(new)
