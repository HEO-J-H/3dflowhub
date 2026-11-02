"""공모전·게임 잼·3D 챌린지 (/events/) — 마감이 있는 '참가할 기회'를 한곳에 (사장님 제안 2026-11-03).

출처 (목록 페이지에서 제목·주최·마감·링크·대표 그림만, 본문은 원문으로 연결):
  · 위비티 (국내 공모전) — 게임/소프트웨어 전부 + 영상·디자인·예체능·건축 중 3D 관련 단어가 있는 것
  · itch.io 게임 잼 (해외) — 곧 시작·진행 중, 추천(Featured)이거나 참가 200명 이상
  · CGTrader 3D 챌린지 (해외) — 마감 전인 것만
  · BlenderArtists 챌린지 (주간 챌린지·상금 대회) — 본문의 마감 문장에서 날짜
  · 행사·컨퍼런스 (Blender Conference·SIGGRAPH·GDC·Annecy·FMX·Gamescom·지스타·NDC) — 공식 사이트 본문의 날짜만, 주 1회
지난 일정은 자동으로 빠짐. AI 는 행사 날짜 읽기에만(주 1회, 본문에 날짜가 있어야 인정). evolve 가 6시간마다 갱신.
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
    for wait in (0, 20, 60):  # itch.io 는 연달아 부르면 429 (너무 많은 요청) → 기다렸다 다시
        time.sleep(wait)
        try:
            r = requests.get(url, headers=UA, timeout=25)
        except requests.RequestException:
            return ""
        if r.status_code != 429:
            r.encoding = "utf-8"  # itch.io 는 헤더에 charset 이 없어 글자가 깨짐
            return r.text if r.ok else ""
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



# ── BlenderArtists 챌린지 (Discourse 공개 JSON) — 주간 챌린지 'Entries OPEN', 상금 대회 'Deadline: …' ──
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_DATE = re.compile(r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+)?([A-Z][a-z]{2,8})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")
_CLOSE = re.compile(r"(clos\w*|deadline|until|ends?\b|submissions? close)", re.I)


def deadline_in(text: str) -> str:
    """'마감'을 말하는 단어 뒤 120자 안의 첫 날짜 (예: 'Entry closes on Monday ( Mon, Nov 2, 2026', 'Submissions close: October 31, 2026')."""
    for m in _CLOSE.finditer(text):
        d = _DATE.search(text[m.end(): m.end() + 120])
        if d and d.group(1)[:3].lower() in MONTHS:
            try:
                return datetime(int(d.group(3)), MONTHS[d.group(1)[:3].lower()], int(d.group(2))).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return ""


def blenderartists(days: int = 40) -> list[dict]:
    base = "https://blenderartists.org"
    try:
        topics = requests.get(f"{base}/c/contests/l/latest.json", headers=UA, timeout=25).json()["topic_list"]["topics"]
    except Exception:  # noqa: BLE001
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for tp in topics:
        title = tp.get("title", "")
        if tp.get("created_at", "") < cutoff or not re.search(r"OPEN|Deadline|Prize|Contest", title, re.I) or re.search(r"CLOSED", title):
            continue
        try:
            d = requests.get(f"{base}/t/{tp['id']}.json", headers=UA, timeout=25).json()
        except Exception:  # noqa: BLE001
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d["post_stream"]["posts"][0].get("cooked", "")))
        dl = deadline_in(text)
        if not dl or dl < _today():
            continue
        prize = re.search(r"\$\s?[\d,]+(?:\s*in prizes)?", title + " " + text, re.I)
        out.append({"id": "b" + _id(str(tp["id"])), "kind": "3D 챌린지", "region": "해외", "title": title[:120],
                    "org": "BlenderArtists", "fields": "Blender · 3D 아트", "deadline": dl,
                    "prize": prize.group(0) if prize else "", "image": d.get("image_url") or "",
                    "url": f"{base}/t/{tp['id']}", "source": "BlenderArtists"})
        time.sleep(1)
    return out


# ── 행사·컨퍼런스 — 공식 사이트 본문에서 날짜를 읽음 (AI 추출 + 날짜가 본문에 실제로 있는지 확인), 주 1회 ──
CONFERENCES = [
    ("Blender Conference", "https://conference.blender.org/", "해외"),
    ("SIGGRAPH 2027", "https://s2027.siggraph.org/", "해외"),
    ("SIGGRAPH Asia 2026", "https://asia.siggraph.org/2026/", "해외"),
    ("GDC (Game Developers Conference)", "https://gdconf.com/", "해외"),
    ("Annecy 국제 애니메이션 페스티벌", "https://www.annecyfestival.com/", "해외"),
    ("FMX (영화·VFX·게임 컨퍼런스)", "https://fmx.de/", "해외"),
    ("Gamescom", "https://www.gamescom.global/", "해외"),
    ("G-STAR (지스타)", "https://www.gstar.or.kr/", "국내"),
    ("NDC (넥슨 개발자 컨퍼런스)", "https://ndc.nexon.com/", "국내"),
]
CONF_EVERY_DAYS = 7


def conferences() -> list[dict]:
    """공식 사이트 본문만 근거로 다음 개최일. 본문에 그 날짜(일·월)가 없으면 버림 (지어낸 날짜 방지)."""
    import refs
    out = []
    for name, url, region in CONFERENCES:
        f = DIR / f"k{_id(url)}.json"
        old = core._load_json(f, {})
        if old.get("checked_at", "") > (datetime.now(timezone.utc) - timedelta(days=CONF_EVERY_DAYS)).isoformat():
            if old.get("deadline", "") >= _today():
                out.append(old)
            continue
        try:
            text = refs.page_text(url, limit=8000, follow=0)
        except Exception:  # noqa: BLE001
            text = ""
        rec = {"id": f"k{_id(url)}", "kind": "행사·컨퍼런스", "region": region, "title": name, "org": "",
               "url": url, "source": "공식 사이트", "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if len(text) > 300:
            try:
                r = core._parse_json(core.llm(
                    f"Official event website text:\n{text}\n\nToday is {_today()}. Find the NEXT edition's dates of {name} "
                    "stated in this text. Return JSON {\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\", \"city\": \"...\", "
                    "\"quote\": exact short text from the page that states the dates}. If the page does not state future "
                    "dates, return {\"start\": \"\"}.", system="You extract facts only from the given text.",
                    max_tokens=200, json_mode=True))
            except core.LLMBudgetExceeded:
                break
            except Exception:  # noqa: BLE001
                r = {}
            start, end, quote = str(r.get("start", "")), str(r.get("end") or r.get("start") or ""), str(r.get("quote", ""))
            ok = (re.fullmatch(r"\d{4}-\d{2}-\d{2}", start or "x") and end >= _today()
                  and quote and quote[:40].lower() in text.lower()
                  and start[:4] in quote + text[:8000])
            if ok:
                rec.update({"start": start, "deadline": end, "fields": str(r.get("city", ""))[:40], "quote": quote[:200]})
        DIR.mkdir(parents=True, exist_ok=True)
        core._save_json(f, {**old, **rec})
        if rec.get("deadline", "") >= _today():
            out.append(rec)
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
                     ("CGTrader", cgtrader), ("BlenderArtists", blenderartists), ("행사", conferences)):
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
