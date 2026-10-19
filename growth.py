"""
자율 성장 안전장치 — 전략이 '잘못된 방향으로 자라는 것'을 막는다
====================================================================
  CORE_RULES      바뀌지 않는 기본 규칙 (자기개선 대상 아님) — Prime Agent 의 immutable base prompt
  clean_notes     편집 지침 검증: 사이트 주제 밖(다른 사이트 지침 포함)·중복 제거, 개수 상한
  snapshot/rollback  지침이 바뀔 때마다 이전 버전 기록, 새 버전 점수가 확실히 나쁘면 최고 버전으로 되돌림
  risk_of         제안 위험도(low/medium/high) — 자동 모드는 low 만 스스로 수락 (BerriAI 승인 게이트)
  winning_patterns / underperformers  잘 된 글의 형식은 재사용, 안 되는 도구 주제는 줄임 (확대/중단)

참고: Prime Agent(/refine 스냅샷·롤백), BerriAI self-improving-agent(위험도·승인), Hermes Agent(스킬 축적)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import core

CORE_RULES = {
    "site": "3dflowhub",
    "topics": ["3D DCC", "게임 엔진", "VFX", "AI 3D"],
    # 이 사이트와 무관한 주제 — 지침에 들어오면 버린다 (다른 사이트의 제안이 섞이는 것 방지)
    "offtopic_words": ["연금", "국민연금", "기초연금", "중위소득", "건강보험", "노후", "은퇴", "부동산", "주식", "코인",
                       "대출", "세금", "보험료", "요양"],
    "max_notes": 6,
    "rollback_margin": 0.1,       # 새 지침 점수가 최고 버전보다 이만큼 낮으면 되돌림
    "min_runs_to_judge": 3,
    "max_snapshots": 20,
}

# 위험도: low = 되돌리기 쉽고 비용·정책 영향 없음 / medium = 콘텐츠 방향·외부 소스 / high = 설정·비용·인력
RISK = {"keyword_hints": "low", "guide_topic": "low", "glossary": "low",
        "editorial_note": "medium", "add_feed": "medium",
        "set_config": "high", "hire_role": "high", "pause_role": "medium"}
RISK_KO = {"low": "낮음", "medium": "중간", "high": "높음"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def risk_of(action: dict | None) -> str:
    return RISK.get((action or {}).get("type"), "high")


def note_offtopic(note: str) -> bool:
    return any(w in note for w in CORE_RULES["offtopic_words"])


def _norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s)


def _similar(a: str, b: str) -> bool:
    """글자 2-gram 겹침으로 거의 같은 지침 판별 (표현만 조금 다른 중복 제거)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return na == nb
    ga = {na[i:i + 2] for i in range(len(na) - 1)} or {na}
    gb = {nb[i:i + 2] for i in range(len(nb) - 1)} or {nb}
    return len(ga & gb) / min(len(ga), len(gb)) >= 0.8


def clean_notes(notes: list, limit: int | None = None) -> list[str]:
    """주제 밖·중복 지침을 버리고, 나중에 들어온 것을 우선해 상한만큼 남긴다."""
    limit = limit or CORE_RULES["max_notes"]
    out: list[str] = []
    for n in reversed([n.strip() for n in notes if isinstance(n, str) and n.strip()]):
        if note_offtopic(n) or any(_similar(n, o) for o in out):
            continue
        out.append(n)
    return list(reversed(out[:limit]))


def core_rules_text() -> str:
    """LLM 성찰 프롬프트에 붙이는 고정 규칙 (자기개선이 바꿀 수 없음)."""
    return (f"FIXED RULES (never change or contradict): this site covers only {', '.join(CORE_RULES['topics'])}. "
            f"Never write notes about unrelated subjects ({', '.join(CORE_RULES['offtopic_words'][:6])} …). "
            f"At most {CORE_RULES['max_notes']} notes, no duplicates.")


# ─────────────────────────── 스냅샷·롤백 ───────────────────────────
def snapshot(strategy: dict, reason: str) -> None:
    snaps = strategy.setdefault("snapshots", [])
    snaps.append({"at": _now(), "ver": core.strategy_version(strategy.get("prompt_notes", [])),
                  "notes": list(strategy.get("prompt_notes", [])), "reason": reason[:200]})
    strategy["snapshots"] = snaps[-CORE_RULES["max_snapshots"]:]


def set_notes(strategy: dict, notes: list[str], reason: str) -> bool:
    """지침 교체는 반드시 이 함수로 — 검증·스냅샷·병합용 타임스탬프를 한 번에 처리."""
    new = clean_notes(notes)
    if not new or new == strategy.get("prompt_notes"):
        return False
    snapshot(strategy, reason)
    strategy["prompt_notes"] = new
    strategy["notes_updated_at"] = _now()
    return True


def rollback_if_worse(strategy: dict, trajectory: list[dict]) -> str:
    """현재 지침 버전이 충분히 평가됐는데 최고 버전보다 확실히 나쁘면 최고 버전으로 되돌린다."""
    cur_ver = core.strategy_version(strategy.get("prompt_notes", []))
    judged = [t for t in trajectory if t["runs"] >= CORE_RULES["min_runs_to_judge"]]
    cur = next((t for t in judged if t["ver"] == cur_ver), None)
    if not cur or len(judged) < 2:
        return ""
    best = max(judged, key=lambda t: t["score"])
    versions = strategy.get("note_versions", {})
    if best["ver"] == cur_ver or cur["score"] > best["score"] - CORE_RULES["rollback_margin"] \
            or not versions.get(best["ver"]):
        return ""
    if set_notes(strategy, versions[best["ver"]], f"롤백: {cur_ver}({cur['score']}) → {best['ver']}({best['score']})"):
        return f"지침 롤백 {cur_ver}(점수 {cur['score']}) → {best['ver']}(점수 {best['score']})"
    return ""


# ─────────────────────────── 확대/중단 · 성공 패턴 ───────────────────────────
def underperformers(perf: dict, min_posts: int = 6) -> list[str]:
    """글은 많이 썼는데 평균 조회수가 전체 평균의 1/4 미만인 도구 — 덜 쓰도록 성찰 프롬프트에 알림."""
    by = perf.get("by_group", {})
    groups = {k: v for k, v in by.items() if "/" in k}
    if not groups:
        return []
    overall = sum(v["views"] for v in groups.values()) / max(1, sum(v["posts"] for v in groups.values()))
    return sorted(k for k, v in groups.items() if v["posts"] >= min_posts and v["avg"] < overall / 4)[:8]


def winning_patterns(perf: dict) -> list[str]:
    """조회수 상위 글의 제목 형식을 재사용 가능한 패턴으로 요약 (Hermes 식 '잘 된 방법' 축적)."""
    out = []
    for views, title in perf.get("top_posts", [])[:5]:
        if views and title:
            shape = "숫자 포함" if re.search(r"\d", title) else "숫자 없음"
            shape += ", 질문형" if title.rstrip().endswith("?") else ""
            out.append(f"{title} (조회 {views}, {len(title)}자, {shape})")
    return out
