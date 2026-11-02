"""기존 콘텐츠 자동 보강·편집 — 새 소식·새 버전 정보가 들어오면, 그 내용과 관련된 기존 가이드·심화 매뉴얼·툴 비교를 찾아 고쳐 쓴다.

1) 찾기: 최근 저장된 소식·버전별 바뀐 점을 rag 검색으로 기존 페이지와 맞춤 (점수 높은 것만) → refresh_with 에 근거 쌓기
2) 고치기: 기존 내용 + 새 근거(원문 본문) → AI 가 '바뀐 부분만' 고친 전체 + 보강 기록(updates). 새 근거가 기존 내용과 관계없거나
   새 정보가 없으면 그대로 둠 (억지 수정 금지). 고친 뒤 QA 가 다시 보도록 qa_at 지움.
3) 페이지에 '🆕 최근 보강' 상자로 무엇이 언제 왜 바뀌었는지 + 근거 링크 표시.
하루 상한은 품질 성적표 손잡이(refresh_daily). evolve 가 주기적으로 실행.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import core

MATCH_SCORE = 9.0     # rag 점수 — 이 이상만 '같은 기능에 대한 새 정보'로 봄
DAILY_DEFAULT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _targets() -> dict:
    import compare
    import guides
    import manual
    return {"guide": (guides.GUIDE_DIR, {g["id"]: g for g in guides.load_all()}),
            "manual": (manual.DIR, {x["id"]: x for x in manual.load_all()}),
            "compare": (compare.DIR, {x["id"]: x for x in compare.load_all()})}


def find(days: int = 3, per_source: int = 2) -> int:
    """최근 새 정보 → 관련 기존 페이지에 근거로 쌓음. 쌓은 개수 반환."""
    import build_site
    import rag
    import refs
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    srcs = [{"key": f"p:{p['id']}", "title": p["title_ko"], "url": p.get("url", ""),
             "text": f"{p['title_ko']} {p.get('summary', '')}"} for p in build_site.load_posts()
            if p.get("collected_at", "") >= cutoff]
    srcs += [{"key": f"c:{x['id']}", "title": x["title"], "url": x.get("source", ""),
              "text": x["title"] + " " + " ".join(h.get("change", "") for h in x.get("highlights", []))}
             for x in refs.load("change") if x.get("at", "") >= cutoff]
    ix = rag.index(refresh=True)
    tg = _targets()
    kind_of = {"guide": "guide", "manual": "manual", "compare": "compare"}
    added = 0
    for s in srcs:
        for h in ix.search(s["text"], k=per_source, kinds=("guide", "manual", "compare"), min_score=MATCH_SCORE):
            kind = kind_of[h["kind"]]
            hid = h["id"][2:] if kind == "manual" and h["id"].startswith("m-") else h["id"]
            d, have = tg[kind]
            x = have.get(hid)
            if not x or not _really_about(x, kind, s["text"]):
                continue
            done = {k for u in x.get("updates") or [] for k in u.get("source_keys", [])} | {r["key"] for r in x.get("refresh_with") or []}
            if s["key"] in done:
                continue
            x.setdefault("refresh_with", []).append({k: s[k] for k in ("key", "title", "url")})
            core._save_json(d / f"{hid}.json", x)
            added += 1
    return added


GENERIC = {"modifier", "basics", "basic", "tool", "tools", "system", "and", "the", "in", "of", "for", "with", "to", "a",
           "panel", "menu", "editor", "settings", "overview", "workflow", "using", "how", "node", "nodes", "mode",
           "creating", "real", "time", "game", "games", "engine", "engines", "into", "from", "many", "objects", "basics"}


def _really_about(x: dict, kind: str, text: str) -> bool:
    """BM25 만으로는 엉뚱하게 이어짐(다트 선수 'The Nuke' → Blueprint 가이드) → 도구 이름과 기능 이름이 새 근거에 실제로 있어야 함."""
    low = text.lower()
    if kind == "compare":
        words = [w for w in re.findall(r"[a-z][a-z0-9+]+", x.get("task", "").lower()) if w not in GENERIC and len(w) > 3]
        tools = sum(r["tool"].lower() in low for r in x.get("rows") or [])
        return tools >= 1 and sum(w in low for w in words) >= 2
    tool = (x.get("tool") or "").lower()
    alias = {"unreal engine": "unreal", "nvidia omniverse": "omniverse", "substance 3d": "substance", "pixyz studio": "pixyz"}
    if (alias.get(tool, tool) or "~") not in low:
        return False
    words = [w for w in re.findall(r"[a-z][a-z0-9+]+", (x.get("name") or "").lower()) if w not in GENERIC and len(w) > 2]
    return bool(words) and any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)


def _cap() -> int:
    try:
        import scorecard
        return scorecard.knob("refresh_daily")
    except Exception:  # noqa: BLE001
        return DAILY_DEFAULT


def apply(max_n: int = 2) -> list[str]:
    """근거가 쌓인 페이지를 고쳐 씀 (하루 상한)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tg = _targets()
    done_today = sum(1 for _, (_, have) in tg.items() for x in have.values()
                     for u in x.get("updates") or [] if u.get("at", "").startswith(today))
    out = []
    for kind, (d, have) in tg.items():
        for x in have.values():
            if len(out) >= max_n or done_today + len(out) >= _cap() or not core.background_ok(2):
                return out
            if not x.get("refresh_with"):
                continue
            try:
                r = _rewrite(kind, x)
            except core.LLMBudgetExceeded:
                return out
            if r is None:
                continue
            core._save_json(d / f"{x['id']}.json", r)
            out.append(f"{kind}:{x['id']}")
    return out


def _source_text(r: dict) -> str:
    """근거 본문: 우리가 저장한 소식 글(요약·섹션·해설)이나 버전 정리 — 구글 뉴스 주소는 원문을 못 읽으므로."""
    import refs
    kind, _, rid = r["key"].partition(":")
    if kind == "p":
        p = core._load_json(core.POSTS_DIR / f"{rid}.json", {})
        return " ".join([p.get("summary", ""), p.get("insight", "")] + [f"{s.get('heading', '')}: {s.get('body', '')}"
                        for s in p.get("sections") or [] if isinstance(s, dict)])
    if kind == "c":
        x = core._load_json(refs.CHANGE_DIR / f"{rid}.json", {})
        return x.get("summary", "") + " " + " ".join(f"{h.get('area', '')}: {h.get('change', '')}" for h in x.get("highlights", []))
    return ""


EDITABLE = {"guide": ("summary", "when", "steps", "params", "examples", "mistakes"),
            "manual": ("overview", "access", "options", "modes", "recipes", "performance", "troubleshoot", "versions"),
            "compare": ("summary", "rows", "pick", "handoff", "apply", "pitfalls")}


def _rewrite(kind: str, x: dict) -> dict | None:
    import refs
    used = x["refresh_with"][:3]
    news = [f"[{r['title']}] {r.get('url', '')}\n{_source_text(r)[:4000]}" for r in used]
    cur = {k: x.get(k) for k in EDITABLE[kind]}
    prompt = ("You maintain a Korean 3D learning page. New information arrived. Update the page ONLY where the new information "
              "changes or adds something real (new option, changed menu path, new version behaviour, new workflow). "
              "Keep everything else exactly as is, same JSON shape and language. Never invent facts beyond the new sources.\n"
              f"Current page ({kind}): {cur}\n\nNew sources:\n" + "\n\n".join(news) + "\n\n"
              'Return JSON {"changed": true/false, "page": {same keys as current, full updated values}, '
              '"what": one Korean sentence — what was updated and why (for readers)}. '
              'If nothing relevant or new, return {"changed": false}.')
    try:
        out = core._parse_json(core.llm(prompt, system="You are a careful technical editor." +
                                        core.playbook("common", "guide_writer", limit=6000), max_tokens=3000, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("보강 실패 %s: %s", x["id"], e)
        return None
    srcs = used
    x["refresh_with"] = x["refresh_with"][3:]  # 아직 안 읽은 근거는 다음 차례에
    if not x["refresh_with"]:
        x.pop("refresh_with")
    if out.get("changed") and isinstance(out.get("page"), dict):
        page = out["page"]
        for k in EDITABLE[kind]:
            v = page.get(k)
            if v and (type(v) is type(x.get(k)) or x.get(k) is None):
                x[k] = v
        x["updates"] = (x.get("updates") or []) + [{"at": _now(), "what": str(out.get("what") or "")[:200],
                                                     "sources": [{"title": s["title"], "url": s.get("url", "")} for s in srcs],
                                                     "source_keys": [s["key"] for s in srcs]}]
        x.pop("qa_at", None)  # 고친 내용은 QA 가 다시 본다
    else:  # 새 정보 없음 — 같은 근거로 다시 보지 않게 기록만
        x["updates"] = (x.get("updates") or []) + [{"at": _now(), "what": "", "source_keys": [s["key"] for s in srcs], "skipped": True}]
    return x
