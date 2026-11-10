"""🧪 QA 직원 — 사장님 요청(2026-11): 품질을 사람 대신 꾸준히 검사하고, 고칠 수 있는 건 바로 다시 만들게 한다.

1) 기계 검사 (AI 안 씀, 전부): 그림·영상 없음, 빈 섹션, 남은 자리표시(TODO·lorem·[]), 깨진 글자, 같은 문장 반복, 영어만 있는 본문
2) AI 검수 (표본, 하루 상한): 최근 콘텐츠를 공식 문서·원문과 대조해 정확성·이해하기 쉬움·그림 도움·사이트 원칙 점수
   → 6점 미만: qa_redo 표시 → 각 모듈이 다시 만듦(가이드·매뉴얼·비교) / 소식 글은 보강 대기열로
3) 같은 문제가 반복되면(같은 종류에서 3건 이상) 글쓰기 지침(editorial_note)을 관리자 제안으로 — 원인을 고침
결과: memory/qa_report.json (현황판·관리자 snapshot), 업무 일지.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from datetime import datetime, timezone

import core

REPORT_PATH = core.ROOT / "memory" / "qa_report.json"
PASS = 6          # AI 검수 점수가 이보다 낮으면 다시 만들기
SAMPLE = 3        # 한 번에 AI 로 검수할 개수
# 남은 자리표시 — 대소문자 구분 (Houdini 'Null' 노드·'Nanite' 같은 정상 용어는 걸리지 않게)
PLACEHOLDER = re.compile(r"\bTODO\b|\bFIXME\b|[Ll]orem ipsum|\{\{|\}\}|\[object Object\]|\bNaN\b")
RAW_STRUCT = re.compile(r"\{'(step|description|heading|body)'\s*:")  # 날것 데이터 (11/04 직접 해 보기)
TICS = ("특히", "파이프라인", "워크플로", "효율", "실무자라면", "유용합니다", "향후", "기대됩니다", "주목할 만한", "시작하려면")
MOJIBAKE = re.compile(r"[ÃÂ][\x80-\xbf]|ì[\x80-\xbf]|�")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return " ".join(_text(v) for k, v in x.items() if k not in ("id", "url", "src", "doc", "videos", "images", "at"))
    if isinstance(x, list):
        return " ".join(_text(v) for v in x)
    return ""


def items() -> list[dict]:
    """검사 대상: (종류, 데이터, 저장 경로)."""
    import build_site
    import compare
    import guides
    import manual
    import refs
    out = [{"kind": "guide", "x": g, "path": guides.GUIDE_DIR / f"{g['id']}.json"} for g in guides.load_all()]
    out += [{"kind": "manual", "x": x, "path": manual.DIR / f"{x['id']}.json"} for x in manual.load_all()]
    out += [{"kind": "compare", "x": x, "path": compare.DIR / f"{x['id']}.json"} for x in compare.load_all()]
    out += [{"kind": "fix", "x": x, "path": refs.FIX_DIR / f"{x['id']}.json"} for x in refs.load("fix")]
    posts = sorted(build_site.load_posts(), key=lambda p: p.get("collected_at", ""), reverse=True)[:300]
    out += [{"kind": "post", "x": p, "path": core.POSTS_DIR / f"{p['id']}.json"} for p in posts]
    return out


def mechanical(it: dict) -> list[str]:
    """AI 없이 찾을 수 있는 문제들."""
    x, k = it["x"], it["kind"]
    body = _text({kk: v for kk, v in x.items() if kk not in ("title", "title_ko", "name", "tool", "error")})
    probs = []
    has_visual = bool(x.get("videos") or x.get("images") or x.get("shots") or (x.get("media") or {}).get("image")
                      or (x.get("media") or {}).get("video") or any(r.get("video") for r in x.get("rows") or []))
    if not has_visual and (k != "manual" or x.get("visuals_at")):
        probs.append("그림·영상 없음")
    if PLACEHOLDER.search(body):
        probs.append("자리표시 문구 남음")
    if MOJIBAKE.search(body):
        probs.append("깨진 글자")
    hangul = len(re.findall(r"[가-힣]", body))
    if body and hangul < len(body) * 0.15:
        probs.append("한국어 설명이 거의 없음")
    sents = [s.strip() for s in re.split(r"[.!?。]\s", body) if len(s.strip()) > 25]
    if sents and len(sents) - len(set(sents)) >= 2:
        probs.append("같은 문장 반복")
    raw = " ".join(str(v) for v in (x.get("try_it") or []))
    if RAW_STRUCT.search(raw) or RAW_STRUCT.search(body):
        probs.append("날것 데이터가 글에")
    tics = [w for w in TICS if w in body]
    if len(tics) >= 3:
        probs.append("상투어 반복(" + "·".join(tics[:4]) + ")")
    if k == "guide" and len(x.get("steps") or []) < 3:
        probs.append("따라 하기 단계가 너무 적음")
    if k == "manual" and len(x.get("options") or []) < 4:
        probs.append("옵션이 너무 적음")
    return probs


def ai_review(it: dict) -> dict | None:
    """공식 문서(있으면)·원문과 대조한 검수. {"score":0-10, "defects":[...], "fix_hint": str}"""
    x = it["x"]
    src = ""
    url = x.get("doc") or x.get("source") or x.get("url") or ""
    if url.startswith("http") and "google.com/search" not in url and "news.google.com" not in url:
        try:
            import refs
            src = refs.page_text(url, limit=6000, follow=0)
        except Exception:  # noqa: BLE001
            src = ""
    content = _text({kk: v for kk, v in x.items() if kk not in ("videos", "images", "shots", "media", "at", "visuals_at")})[:5000]
    prompt = (f"You are a strict QA editor for a Korean 3D learning site. Content type: {it['kind']}.\n"
              + (f"Source / official documentation (ground truth):\n{src}\n\n" if src else "No source text: judge by well-established facts only.\n")
              + f"Page content:\n{content}\n\n"
              "Check: (1) factual errors vs source, invented menu paths / values / versions, (2) can a Korean artist actually "
              "learn and follow it, (3) Korean quality (unnatural translation, wrong official English UI names), "
              "(4) missing key information. Return JSON {\"score\": 0-10 integer (6 = acceptable), "
              "\"defects\": [up to 4 short Korean strings, concrete], \"fix_hint\": one Korean sentence on how the writer "
              "should avoid this next time}.")
    try:
        out = core._parse_json(core.llm(prompt, system="You are a meticulous technical QA reviewer." + core.playbook("common", "qa", limit=6000),
                                        max_tokens=700, json_mode=True))
        return {"score": int(out.get("score", 10)), "defects": [str(d)[:120] for d in out.get("defects") or []][:4],
                "fix_hint": str(out.get("fix_hint") or "")[:200]}
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("QA 검수 실패 %s: %s", x.get("id"), e)
        return None


FB_MIN_DOWN = 2  # 👎 가 이만큼 이상이고 👍 보다 많으면 다시 쓰기·보강


def feedback_targets() -> list[str]:
    """독자 👎 가 쌓인 페이지 → 가이드·비교는 qa_redo(다시 만들기), 오류 해결은 qa_redo, 소식은 보강 대기열.
    한 페이지는 한 번만 (fb_acted 기록) — 고친 뒤 다시 👎 가 쌓이면 그때 또."""
    import compare
    import guides
    import refs
    fb = (core._load_json(core.ROOT / "memory" / "feedback.json", {}).get("pages") or {})
    acted = []
    for path, d in fb.items():
        if d.get("down", 0) < FB_MIN_DOWN or d["down"] <= d.get("up", 0):
            continue
        m = re.search(r"/(learn|compare|fix)/([^/]+)/", path) or re.search(r"/p/([^/]+)\.html", path)
        if not m:
            continue
        if path.find("/p/") >= 0:
            f = core.POSTS_DIR / f"{m.group(1)}.json"
        else:
            kind, pid = m.group(1), m.group(2)
            f = {"learn": guides.GUIDE_DIR, "compare": compare.DIR, "fix": refs.FIX_DIR}[kind] / f"{pid}.json"
        x = core._load_json(f, None)
        if not isinstance(x, dict) or x.get("fb_acted") == d["down"]:
            continue
        if "/p/" in path:
            x.pop("enriched", None)
            x["qa_flag"] = True
        else:
            x["qa_redo"] = True
        x["fb_acted"] = d["down"]
        core._save_json(f, x)
        acted.append(path)
    return acted


def run(sample: int = SAMPLE) -> dict:
    all_items = items()
    fb_redo = feedback_targets()  # 독자 👎 먼저
    mech = []
    for it in all_items:
        p = mechanical(it)
        if p:
            mech.append({"kind": it["kind"], "id": it["x"].get("id"), "title": it["x"].get("title") or it["x"].get("title_ko"),
                         "problems": p})
    # AI 검수: 아직 안 본 것 중 최근·무작위 (같은 걸 반복해서 보지 않게 qa_at 기록)
    fresh = [it for it in all_items if not it["x"].get("qa_at") and it["kind"] != "post"]
    fresh += [it for it in all_items if not it["x"].get("qa_at") and it["kind"] == "post"][:40]
    random.shuffle(fresh)
    reviewed, redo = [], []
    for it in fresh[:sample]:
        if not core.background_ok(1):
            break
        try:
            r = ai_review(it)
        except core.LLMBudgetExceeded:
            break
        if not r:
            continue
        x = core._load_json(it["path"], None) or it["x"]
        x["qa_at"], x["qa"] = _now(), r
        if r["score"] < PASS:
            if it["kind"] == "post":
                x.pop("enriched", None)
                x["qa_flag"] = True   # 소식 글: 보강 대기열로 (core.enrich_thin_posts)
            else:
                x["qa_redo"] = True   # 가이드·매뉴얼·비교: 다음 생성 때 다시 만듦
            redo.append(f"{it['kind']}:{x.get('id')}")
        core._save_json(it["path"], x)
        reviewed.append({"kind": it["kind"], "id": x.get("id"), "title": x.get("title") or x.get("title_ko"), **r})
    prev = core._load_json(REPORT_PATH, {})
    history = (prev.get("reviews", []) + reviewed)[-200:]
    low = Counter(r["kind"] for r in history if r["score"] < PASS)
    report = {"at": _now(), "checked": len(all_items), "mechanical_count": len(mech),
              "mechanical_by_problem": Counter(p for m in mech for p in m["problems"]).most_common(),
              "mechanical": mech[:60], "reviews": history,
              "avg_score": round(sum(r["score"] for r in history) / len(history), 1) if history else None,
              "low_by_kind": dict(low), "redo_now": redo, "reader_downvoted": fb_redo}
    core._save_json(REPORT_PATH, report)
    _escalate(history)
    return report


def _escalate(history: list[dict]) -> None:
    """같은 종류에서 낮은 점수가 3건 이상 → 원인(글쓰기 지침)을 고치는 제안 (자동 수락되는 안전한 행동)."""
    import manager
    by_kind: dict[str, list] = {}
    for r in history[-60:]:
        if r["score"] < PASS and r.get("fix_hint"):
            by_kind.setdefault(r["kind"], []).append(r)
    for kind, rs in by_kind.items():
        if len(rs) < 3:
            continue
        title = f"QA: {kind} 품질 반복 문제 — 글쓰기 지침 보강"
        if manager.similar_open(title, "3dflowhub"):
            continue
        hint = Counter(r["fix_hint"] for r in rs).most_common(1)[0][0]
        manager._append({"at": _now(), "kind": "proposal", "id": "p-qa" + datetime.now().strftime("%m%d%H%M") + kind[:3],
                         "title": title, "by": "🧪 QA", "site": "3dflowhub", "category": "콘텐츠",
                         "evidence": f"최근 검수 {kind} {len(rs)}건이 {PASS}점 미만: " + "; ".join(
                             f"{r.get('title', '')[:30]}({r['score']}) {', '.join(r['defects'][:1])}" for r in rs[:4]),
                         "proposal": hint, "expected": "같은 결함이 새 콘텐츠에서 반복되지 않음", "effort": "낮음",
                         "action": {"type": "editorial_note", "note": hint[:200]}})


QA_ROLE = {"name": "🧪 QA", "deliverables": ["qa"], "every_hours": 6, "daily_calls": 6, "site": "3dflowhub",
           "mission": "사이트 콘텐츠 품질 검사 — 기계 검사(그림·영상 없음, 깨진 글자, 자리표시, 반복 문장) 전체 + 공식 문서·원문과 "
                      "대조한 AI 검수(표본). 6점 미만은 다시 만들기·보강 대기열로 보내고, 같은 문제가 반복되면 글쓰기 지침을 고친다.",
           "playbook": "- 사장님 기준: 배울 수 있는가, 그림·영상이 있는가, 사실인가.\n- 점수는 엄격하게: 지어낸 메뉴 경로·값은 즉시 4점 이하.\n"
                       "- 한 번에 몇 개만 깊게. 같은 걸 반복해서 보지 않는다.\n- 문제를 고치는 건 원인(지침)부터."}
