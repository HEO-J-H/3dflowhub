"""명령별 심화 매뉴얼 (/manual/) — 기초 가이드의 다음 단계: 한 명령(모디파이어·도구·노드)을 매뉴얼처럼 끝까지.

기초 가이드는 '처음 써 보기'(옵션 6개까지). 심화 매뉴얼은 모든 주요 옵션의 값 범위·기본값·효과·실무 팁, 모드별 차이,
다른 기능과 조합한 응용 레시피, 무거울 때 대처, 증상별 문제 해결까지 — 공식 문서 본문을 근거로(있으면 우선).
저장: content/manual/<가이드 id>.json, 하루 상한. 가이드 페이지에 '심화 매뉴얼' 링크로 연결.
"""
from __future__ import annotations

from datetime import datetime, timezone

import core

DIR = core.ROOT / "content" / "manual"
DAILY_MAX = 8
TOOL_ORDER = ["Blender", "3ds Max", "Houdini", "Unreal Engine", "Maya", "ZBrush", "Substance 3D", "NVIDIA Omniverse"]


def load_all() -> list[dict]:
    if not DIR.exists():
        return []
    return [x for x in (core._load_json(f, None) for f in sorted(DIR.glob("*.json"))) if isinstance(x, dict)]


def _official(url: str) -> bool:
    return bool(url) and "google.com/search" not in url and "?query=" not in url and "search?" not in url


def pending(guides_: list[dict] | None = None) -> list[dict]:
    """아직 매뉴얼이 없는 가이드 — 공식 문서 근거가 있는 것 먼저, 많이 쓰는 툴 순."""
    import guides
    have = {f.stem for f in DIR.glob("*.json")} if DIR.exists() else set()
    gstate = core.curation_state()
    gs = [g for g in (guides_ if guides_ is not None else guides.load_all())
          if g["id"] not in have and gstate.get("learn:" + g["id"]) != "hide"]
    rank = {t: i for i, t in enumerate(TOOL_ORDER)}
    return sorted(gs, key=lambda g: (not _official(g.get("doc", "")), rank.get(g["tool"], 99), g["id"]))


def make(g: dict) -> dict | None:
    doc = ""
    if _official(g.get("doc", "")):
        try:
            import refs
            doc = refs.page_text(g["doc"], limit=12000, follow=4)
        except Exception:  # noqa: BLE001
            doc = ""
    try:
        from guides import _site_context
        site = _site_context(f"{g['tool']} {g['name']} {g['title']}")
    except Exception:  # noqa: BLE001
        site = ""
    basics = {k: g.get(k) for k in ("summary", "steps", "params")}
    prompt = (site + f"Write an in-depth Korean reference manual for ONE command: {g['tool']} — {g['name']}.\n"
              + (f"Official documentation (ground truth — prefer it; do not contradict it):\n{doc}\n" if doc else
                 "No documentation text: include only well-established facts; omit any value / default you are unsure of.\n")
              + f"Beginner page already on the site (go deeper, do not repeat it):\n{basics}\n"
              "Keep official English UI names. Return JSON:\n"
              ' "overview": 2-3 Korean sentences — what it really does internally,\n'
              ' "access": Korean — every way to open it (menu path, shortcut, search),\n'
              ' "options": up to 14 {"name": English UI name, "value": range / default if known else "", '
              '"effect": Korean, "tip": Korean practical tip},\n'
              ' "modes": up to 4 {"name", "desc": Korean} — sub-modes / methods and how they differ ([] if none),\n'
              ' "recipes": 3-4 {"title": Korean, "steps": 3-6 Korean steps} — applied workflows combining it with other features,\n'
              ' "performance": 2-4 Korean tips when it is slow / heavy,\n'
              ' "troubleshoot": 3-5 {"symptom": Korean, "fix": Korean},\n'
              ' "versions": Korean note on version differences only if documented, else ""')
    try:
        out = core._parse_json(core.llm(prompt, system="You are a senior 3D technical director writing precise Korean manuals."
                                        + core.playbook("common", "guide_writer", limit=3000), max_tokens=3200, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("심화 매뉴얼 생성 실패 %s: %s", g["id"], e)
        return None
    fx = core.fix_terms
    opts = [{"name": str(o.get("name", ""))[:50], "value": str(o.get("value", ""))[:60], "effect": fx(str(o.get("effect", ""))),
             "tip": fx(str(o.get("tip", "")))} for o in out.get("options") or [] if isinstance(o, dict) and o.get("name")][:14]
    recipes = [{"title": fx(str(r.get("title", ""))), "steps": [fx(str(s)) for s in r.get("steps") or []][:6]}
               for r in out.get("recipes") or [] if isinstance(r, dict) and r.get("title") and r.get("steps")][:4]
    if len(opts) < 4 or not recipes or not out.get("overview"):  # 기초 가이드보다 깊지 않으면 올리지 않음
        return None
    return {"id": g["id"], "guide_id": g["id"], "tool": g["tool"], "name": g["name"], "title": g["title"],
            "overview": fx(str(out["overview"])), "access": fx(str(out.get("access", ""))), "options": opts,
            "modes": [{"name": str(m.get("name", "")), "desc": fx(str(m.get("desc", "")))}
                      for m in out.get("modes") or [] if isinstance(m, dict) and m.get("name")][:4],
            "recipes": recipes, "performance": [fx(str(x)) for x in out.get("performance") or []][:4],
            "troubleshoot": [{"symptom": fx(str(t.get("symptom", ""))), "fix": fx(str(t.get("fix", "")))}
                             for t in out.get("troubleshoot") or [] if isinstance(t, dict) and t.get("symptom")][:5],
            "versions": fx(str(out.get("versions") or "")), "doc": g.get("doc", ""), "grounded": bool(doc),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def write(max_new: int = 2) -> list[str]:
    if not core.background_ok(max_new):
        return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    import scorecard  # 하루 상한은 품질 성적표가 스스로 조절 (기본 DAILY_MAX)
    left = scorecard.knob("manual_daily") - sum(1 for x in load_all() if x.get("at", "").startswith(today))
    done = []
    for g in pending()[:max(0, min(max_new, left))]:
        try:
            x = make(g)
        except core.LLMBudgetExceeded:
            break
        if x:
            core._save_json(DIR / f"{x['id']}.json", x)
            done.append(x["title"])
    return done
