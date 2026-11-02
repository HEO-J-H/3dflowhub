"""공모전·게임 잼·3D 챌린지 (/events/) — 마감이 있는 '참가할 기회'를 한곳에 (사장님 제안 2026-11-03).

출처 (목록 페이지에서 제목·주최·마감·링크·대표 그림만, 본문은 원문으로 연결):
  · 위비티 (국내 공모전) — 게임/소프트웨어 전부 + 영상·디자인·예체능·건축 중 3D 관련 단어가 있는 것
  · itch.io 게임 잼 (해외) — 곧 시작·진행 중, 추천(Featured)이거나 참가 200명 이상
  · CGTrader 3D 챌린지 (해외) — 마감 전인 것만
지난 일정은 자동으로 빠짐. AI 를 쓰지 않음. evolve 가 6시간마다 갱신.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

import core

DIR = core.ROOT / "content" / "events"
UA = {"User-Agent": "Mozilla/5.0 (3dflowhub events; +https://heo-j-h.github.io/3dflowhub/)"}
KST = timezone(timedelta(hours=9))
WEVITY = "https://www.wevity.com/"
WEVITY_CATS = {21: "게임/소프트웨어", 10: "영상/UCC/사진", 19: "디자인/캐릭터/웹툰", 26: "예체능/미술/음악", 24: "건축/건설/인테리어"}
# 게임 외 분야는 '제목'에 3D·게임·애니 관련 단어가 있어야 (분야 이름 '영상/UCC/사진'만으로는 사진·맛집 숏폼까지 들어옴)
RELEVANT = re.compile(r"3D|3d|게임|애니메이션|VFX|모델링|캐릭터|메타버스|XR|VR|그래픽|CG|시각효과|언리얼|유니티|블렌더|"
                      r"디지털 ?트윈|인터랙티브|버추얼|미디어 ?아트|모션 ?그래픽|렌더|시뮬레이션|제페토|로블록스|웹툰|일러스트|AI 영상")
ITCH_MIN_JOINED = 200


def _id(*parts: str) -> str:
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:10]


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _get(url: str) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.encoding = "utf-8"  # itch.io 는 헤더에 charset 이 없어 글자가 깨짐
        return r.text if r.ok else ""
    except requests.RequestException:
        return ""


def _og(html: str) -> str:
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html)
    return m.group(1) if m else ""


def wevity(pages: int = 2) -> list[dict]:
    from bs4 import BeautifulSoup
    out = []
    for cidx, field in WEVITY_CATS.items():
        for gp in range(1, pages + 1):
            soup = BeautifulSoup(_get(f"{WEVITY}?c=find&s=1&gub=1&cidx={cidx}&gp={gp}"), "html.parser")
            for li in soup.select("ul.list li"):
                a = li.select_one(".tit a")
                day = li.select_one(".day")
                if not a or not day:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).replace("SPECIAL", "").replace("IDEA", "").strip()
                sub = li.select_one(".sub-tit")
                fields = (sub.get_text(" ", strip=True).replace("분야 :", "").strip() if sub else field)
                if cidx != 21 and not RELEVANT.search(title):
                    continue  # 게임 외 분야는 3D·영상·게임 관련만
                m = re.search(r"D-(\d+)", day.get_text())
                if not m:
                    continue
                deadline = (datetime.now(KST) + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
                organ = li.select_one(".organ")
                out.append({"id": "w" + _id(a["href"]), "kind": "공모전", "region": "국내", "title": title[:120],
                            "org": organ.get_text(strip=True)[:60] if organ else "", "fields": fields[:80],
                            "deadline": deadline, "url": urljoin(WEVITY, a["href"]), "source": "위비티"})
            time.sleep(1)
    return out


def itch(kind: str = "upcoming") -> list[dict]:
    from bs4 import BeautifulSoup
    html = _get(f"https://itch.io/jams/{kind}")
    out = []
    for j in BeautifulSoup(html, "html.parser").select("div.jam"):
        a = j.select_one("h3 a") or j.select_one("a[href^='/jam/']")
        if not a:
            continue
        text = re.sub(r"\s+", " ", j.get_text(" ", strip=True))
        joined = int((re.search(r"([\d,]+) joined", text) or [0, "0"])[1].replace(",", ""))
        featured = "Featured" in text
        if not featured and joined < ITCH_MIN_JOINED:
            continue
        dates = re.findall(r"(\d{4}-\d{2}-\d{2})T", text)
        lasts = re.search(r"Lasts ([\d]+ (?:day|days|hour|hours|week|weeks|month|months|year|years))", text)
        host = re.search(r"Hosted by (.+?) (?:Starts|Ends|Submission)", text)
        start = dates[0] if dates and kind == "upcoming" else ""
        end = dates[0] if dates and kind == "in-progress" else ""
        if start and lasts and not end:
            n, unit = lasts.group(1).split()
            days = int(n) * {"hour": 0, "hours": 0, "day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30,
                             "year": 365, "years": 365}[unit]
            end = (datetime.fromisoformat(start) + timedelta(days=max(days, 1))).strftime("%Y-%m-%d")
        if not end or end > (datetime.now(KST) + timedelta(days=200)).strftime("%Y-%m-%d"):
            continue  # 몇 년짜리 상시 잼 등은 제외
        cover = j.select_one(".jam_cover")
        out.append({"id": "i" + _id(a["href"]), "kind": "게임 잼", "region": "해외", "title": a.get_text(strip=True)[:120],
                    "org": (host.group(1) if host else "")[:60], "fields": f"게임 제작 · {lasts.group(1) if lasts else ''}".strip(" ·"),
                    "start": start, "deadline": end, "joined": joined, "featured": featured,
                    "image": cover.get("data-background_image", "") if cover else "",
                    "url": urljoin("https://itch.io", a["href"]), "source": "itch.io"})
    return out


def cgtrader() -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_get("https://www.cgtrader.com/challenges"), "html.parser")
    links = list(dict.fromkeys(a["href"] for a in soup.select("a[href^='/challenges/']") if a.get_text(strip=True)))[:12]
    out = []
    for href in links:
        html = _get(urljoin("https://www.cgtrader.com", href))
        m = re.search(r'challenge-info__deadline">\s*<b>([^<]+)</b>\s*([0-9-]{10})', html)
        if not m or "ended" in m.group(1).lower():
            continue  # 끝난 챌린지
        title = re.search(r"<title>([^<|]+)", html)
        prize = re.search(r"total reward is ([^<.]{3,60})", html)
        out.append({"id": "c" + _id(href), "kind": "3D 챌린지", "region": "해외",
                    "title": (title.group(1).strip() if title else href.split("/")[-1])[:120], "org": "CGTrader",
                    "fields": "3D 모델링", "deadline": m.group(2), "prize": prize.group(1).strip() if prize else "",
                    "image": _og(html), "url": urljoin("https://www.cgtrader.com", href), "source": "CGTrader"})
        time.sleep(1)
    return out


def load_all(include_past: bool = False) -> list[dict]:
    if not DIR.exists():
        return []
    xs = [x for x in (core._load_json(f, None) for f in DIR.glob("*.json")) if isinstance(x, dict)]
    today = _today()
    return sorted([x for x in xs if include_past or x.get("deadline", "") >= today], key=lambda x: x.get("deadline", ""))


def refresh() -> dict:
    """출처를 다시 읽어 저장 (같은 일정은 갱신), 지난 일정 파일은 정리."""
    got, errors = [], []
    for name, fn in (("위비티", wevity), ("itch 예정", lambda: itch("upcoming")), ("itch 진행", lambda: itch("in-progress")),
                     ("CGTrader", cgtrader)):
        try:
            got += fn()
        except Exception as e:  # noqa: BLE001 — 출처 하나가 막혀도 나머지는 계속
            errors.append(f"{name}: {str(e)[:80]}")
    DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for x in got:
        f = DIR / f"{x['id']}.json"
        old = core._load_json(f, {})
        if not x.get("image") and x["source"] == "위비티":
            x["image"] = old.get("image") or _og(_get(x["url"]))  # 위비티는 상세 페이지 대표 그림 (처음 한 번만)
        core._save_json(f, {**old, **x, "seen_at": now, "first_seen": old.get("first_seen") or now})
    old_cut = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    removed = 0
    for f in DIR.glob("*.json"):  # 마감 2주 지난 일정 파일은 정리 (사이트엔 마감 전 것만 보임)
        if core._load_json(f, {}).get("deadline", "9999") < old_cut:
            f.unlink()
            removed += 1
    return {"fetched": len(got), "active": len(load_all()), "removed": removed, "errors": errors}


if __name__ == "__main__":
    print(refresh())
