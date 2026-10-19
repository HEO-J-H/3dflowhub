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
    site = "https://heo-j-h.github.io/3dflowhub/showcase/"
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
