"""품질 성적표 + 스스로 조절 — '배울 수 있는 사이트'가 되고 있는지 숫자로 보고, 모자라면 속도를 스스로 올린다.

사장님 방향(knowledge/common.md '운영자 방향')을 지표로 옮긴 것:
  그림·영상이 있는가 / 기초 → 심화 매뉴얼 → 툴 비교로 이어지는가 / 빈약·중복 글이 줄고 있는가 / 검색 구조가 깨끗한가
결과: memory/scorecard.json (현황판·AI 관리자 snapshot 이 읽음), memory/tuning.json (각 모듈의 하루 상한·속도).
조절은 정해진 범위 안에서만, AI 여유가 있을 때만 올리고, 목표를 넘기면 원래 속도로 내린다 (사람 개입 없이 안전하게).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import core

SCORE_PATH = core.ROOT / "memory" / "scorecard.json"
TUNING_PATH = core.ROOT / "memory" / "tuning.json"

# 조절 손잡이: (기본값, 최소, 최대, 한 번에 바꾸는 폭)
KNOBS = {
    "visuals_posts_per_run": (25, 10, 60, 10),   # 소식 글 그림 보강 (AI 안 씀)
    "visuals_refs_per_run": (6, 3, 20, 3),        # 참고 페이지 그림·영상 (AI 안 씀)
    "enrich_daily": (20, 10, 40, 5),              # 빈약한 글 보강 (AI)
    "manual_daily": (8, 4, 16, 2),                # 심화 매뉴얼 (AI)
    "compare_daily": (4, 2, 8, 1),                # 툴 비교 (AI)
    "refresh_daily": (6, 3, 12, 2),               # 기존 페이지 보강 (AI)
}
# 지표 → (목표, 모자랄 때 올릴 손잡이, AI 를 쓰는가)
TARGETS = {
    "post_image_pct": (90, "visuals_posts_per_run", False),
    "ref_visual_pct": (95, "visuals_refs_per_run", False),
    "thin_pct": (8, "enrich_daily", True),            # 낮을수록 좋음
    "manual_coverage_pct": (60, "manual_daily", True),
    "compare_coverage_pct": (100, "compare_daily", True),
}
LOWER_IS_BETTER = {"thin_pct", "dup_titles"}


def knob(name: str) -> int:
    """모듈이 읽는 현재 값 (조절된 값이 없으면 기본값)."""
    base, lo, hi, _ = KNOBS[name]
    v = core._load_json(TUNING_PATH, {}).get(name, base)
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return base


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 100.0


def measure() -> dict:
    import build_site
    import compare
    import guides
    import manual
    import recipes
    import refs
    posts = build_site.load_posts()
    recent = sorted(posts, key=lambda p: p.get("collected_at", ""), reverse=True)[:600]
    has_img = sum(bool((p.get("media") or {}).get("image") or (p.get("media") or {}).get("video")) for p in recent)
    gstate = core.curation_state()
    gs = [g for g in guides.load_all() if gstate.get("learn:" + g["id"]) != "hide"]
    mans = manual.load_all()
    refs_all = refs.load("fix") + refs.load("change") + compare.load_all() + mans + recipes.load_all()
    ref_vis = sum(bool(x.get("videos") or x.get("images") or x.get("shots") or x.get("hero")
                       or any(r.get("video") for r in x.get("rows") or [])) for x in refs_all)
    seo = core._load_json(core.ROOT / "memory" / "seo_audit.json", {})
    blender_mans = [m for m in mans if m["tool"] == "Blender" and "shots" in m]
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "post_image_pct": _pct(has_img, len(recent)),
        "ref_visual_pct": _pct(ref_vis, len(refs_all)),
        "thin_pct": _pct(sum(build_site.is_thin(p) for p in recent), len(recent)),
        "manual_coverage_pct": _pct(len(mans), len(gs)),
        "manual_render_pct": _pct(sum(bool(m.get("shots")) for m in blender_mans), len(blender_mans)),
        "compare_coverage_pct": _pct(len(compare.load_all()), len(compare.TOPICS)),
        "guides_with_video_pct": _pct(sum(bool(g.get("videos")) for g in gs), len(gs)),
        "dup_titles": seo.get("dup_title_count", 0), "seo_orphans": seo.get("orphan_count", 0),
        "counts": {"posts": len(posts), "guides": len(gs), "manuals": len(mans), "compare": len(compare.load_all()),
                   "fixes": len(refs.load("fix")), "changes": len(refs.load("change")), "recipes": len(recipes.load_all())},
    }


def gaps(score: dict) -> list[dict]:
    """목표 미달 항목 (가장 큰 부족부터) — AI 관리자가 '가장 큰 병목'으로 본다."""
    out = []
    for k, (goal, kn, _ai) in TARGETS.items():
        v = score.get(k)
        if v is None:
            continue
        short = (v - goal) if k in LOWER_IS_BETTER else (goal - v)
        if short > 0:
            out.append({"metric": k, "value": v, "target": goal, "short_by": round(short, 1), "knob": kn})
    return sorted(out, key=lambda g: -g["short_by"] / max(1, g["target"]))


def tune(score: dict) -> list[str]:
    """모자란 지표의 손잡이를 한 칸 올리고, 목표를 넘긴 것은 한 칸 내린다. AI 를 쓰는 손잡이는 AI 여유가 있을 때만 올림."""
    t = core._load_json(TUNING_PATH, {})
    short = {g["knob"] for g in gaps(score)}
    changed = []
    for k, (goal, kn, uses_ai) in TARGETS.items():
        base, lo, hi, step = KNOBS[kn]
        cur = knob(kn)
        if kn in short:
            if uses_ai and not core.background_ok(4):
                continue
            new = min(hi, cur + step)
        else:
            new = max(base, cur - step)  # 목표 달성 → 원래 속도로 천천히
        if new != cur:
            t[kn] = new
            changed.append(f"{kn} {cur}→{new} ({k} {score.get(k)} / 목표 {goal})")
    if changed:
        t["at"] = score["at"]
        t["log"] = (t.get("log", []) + [{"at": score["at"], "changes": changed}])[-30:]
        core._save_json(TUNING_PATH, t)
    return changed


def run() -> dict:
    score = measure()
    score["gaps"] = gaps(score)
    score["tuned"] = tune(score)
    core._save_json(SCORE_PATH, score)
    return score


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
