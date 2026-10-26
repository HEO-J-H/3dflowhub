"""현황판 알림 — 기한(D-day)·만료·확인이 필요한 일을 급한 순서로 모은다.

자동 감지: GitHub 토큰 만료일, 자동 수집 멈춤, AI 한도·리셋, 검토 대기 제안·답변 대기 의견,
          기초 가이드 주제 소진, Search Console 미연결
직접 등록: config.json 의 reminders [{"title", "date": "YYYY-MM-DD", "note"}] (현황판 설정 탭에서 추가·삭제)
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone

from zoneinfo import ZoneInfo

import requests

import core

LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}
ICON = {"error": "🔴", "warning": "🟠", "info": "🔵"}


def _alert(level: str, title: str, detail: str = "", days: int | None = None, key: str = "") -> dict:
    return {"level": level, "title": title, "detail": detail, "days": days, "key": key or title}


def dday(days: int | None) -> str:
    if days is None:
        return ""
    return "만료됨" if days < 0 else "D-DAY" if days == 0 else f"D-{days}"


def token_expiry(repo: str = core.GH_REPO) -> date | None:
    """GH_PAT 만료일: GitHub 이 응답 헤더 GitHub-Authentication-Token-Expiration 으로 알려줌. 모르면 None.
    한 번 알아내면 config.json 의 gh_pat_expires 에 적어 두어 토큰이 없는 PC 현황판에서도 보이게 한다."""
    tok = os.getenv("GH_PAT", "").strip()
    if tok:
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}", timeout=10,
                             headers={"Authorization": f"Bearer {tok}"})
            m = re.search(r"\d{4}-\d{2}-\d{2}", r.headers.get("GitHub-Authentication-Token-Expiration", ""))
            if m:
                return date.fromisoformat(m.group(0))
        except requests.RequestException:
            pass
    saved = core.load_config().get("gh_pat_expires")
    try:
        return date.fromisoformat(saved) if saved else None
    except ValueError:
        return None


def collect(cfg: dict | None = None, runs: list[dict] | None = None, last_run: dict | None = None,
            token_exp: date | None = None) -> list[dict]:
    """알림 목록 (급한 순). runs = GitHub Actions 실행 기록, last_run = memory 의 마지막 수집 기록."""
    cfg = cfg or core.load_config()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()  # 서버(UTC)가 아닌 한국 날짜
    out: list[dict] = []

    # 1) GitHub 토큰 만료
    if token_exp:
        d = (token_exp - today).days
        if d <= 14:
            out.append(_alert("error" if d <= 3 else "warning", f"GitHub 토큰(GH_PAT) 만료 {dday(d)}",
                              f"{token_exp} 만료 — github.com/settings/personal-access-tokens 에서 재발급 후 "
                              "Streamlit Secrets 의 GH_PAT 교체", d, "gh_pat"))
        else:
            out.append(_alert("info", f"GitHub 토큰 만료 {dday(d)}", f"{token_exp} 만료 예정", d, "gh_pat"))
    elif core.CLOUD:
        out.append(_alert("warning", "GitHub 토큰(GH_PAT) 확인 불가", "Secrets 에 GH_PAT 가 없거나 잘못됨 — 저장이 안 됩니다"))

    # 2) 자동 수집 상태
    if runs:
        cur = [r for r in runs if str(r.get("name", "")).startswith("3dflowhub auto")]
        if cur and cur[0].get("conclusion") == "failure":
            out.append(_alert("error", "자동 수집 실패", "GitHub Actions 의 최근 실행이 실패했습니다 — 실행 기록 확인"))
    if last_run and last_run.get("at"):
        try:
            hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last_run["at"])).total_seconds() / 3600
            limit = max(3, core.INTERVALS.get(cfg.get("interval"), 3600) / 3600 * 3)
            if hours > limit:
                out.append(_alert("warning", f"자동 수집이 {int(hours)}시간째 기록 없음",
                                  "GitHub Actions 가 멈췄는지 확인 (heartbeat 워크플로)"))
        except ValueError:
            pass

    # 3) AI 사용량
    cap = core.llm_capacity_left()
    if cap <= 0:
        out.append(_alert("warning", "오늘 AI 사용량 소진", f"{core.llm_reset_kst()} (한국 시간) 리셋 후 자동 재개"))
    elif cap < 30:
        out.append(_alert("info", f"오늘 AI 여력 {cap}회 남음", f"리셋 {core.llm_reset_kst()} (한국 시간)"))

    # 4) AI 관리자
    try:
        import manager
        b = manager.board()
        n_new = sum(1 for p in b["proposals"] if p["status"] == "new")
        if n_new:
            out.append(_alert("info", f"검토할 AI 관리자 제안 {n_new}건", "자동화·진화 탭에서 수락·보류·거절"))
        todo = [p for p in b["proposals"] if p["status"] == "accepted" and not (p.get("action") or {}).get("type")]
        if todo:
            out.append(_alert("info", f"직접 작업 필요한 제안 {len(todo)}건", ", ".join(p["title"] for p in todo[:3])))
    except Exception:
        pass

    # 4.5) 단위 테스트 실패 (수집은 계속되지만 코드가 깨졌다는 신호)
    ts = core._load_json(core.ROOT / "memory" / "tests_status.json", {})
    if ts and not ts.get("ok"):
        out.append(_alert("error", "단위 테스트 실패 — 코드 확인 필요",
                          "수집은 계속 돌지만 최근 코드 변경이 테스트를 깨뜨렸습니다: " + str(ts.get("tail", ""))[-200:]))

    # 4.6) 자가 복구가 최근 24시간에 한 일 (되돌림·고장 발견)
    cut = (datetime.now(timezone.utc).timestamp() - 86400)
    for h in core._load_json(core.ROOT / "memory" / "selfheal.json", [])[-5:]:
        try:
            recent = datetime.fromisoformat(h["at"]).timestamp() > cut
        except (KeyError, ValueError):
            recent = False
        if recent and h.get("kind") in ("heal", "probe"):
            out.append(_alert("info" if h.get("ok") else "warning", "AI 관리자 자가 복구: " + h["text"][:60], h["text"]))

    # 5) 기초 가이드 주제
    try:
        import guides
        left = len(guides.pending())
        if left == 0:
            import manager
            made = sum(1 for g in guides.load_all() if (g.get("at") or "") >= manager._day_start_utc())
            out.append(_alert("info", "기초 가이드 준비된 주제를 모두 작성함" + (f" (오늘 {made}개)" if made else ""),
                              "새 주제는 AI 관리자가 다음 분석 때 자동으로 제안·추가합니다 (직접 추가: guides.py)"))
        elif left <= 5:
            out.append(_alert("info", f"기초 가이드 남은 주제 {left}개", "곧 소진 — 새 주제가 필요합니다"))
    except Exception:
        pass

    # 6) 연결 안 된 기능
    gsc_err = core.load_strategy().get("gsc_error")
    gsc_data = core._load_json(core.ROOT / "memory" / "search_console.json", {})
    if gsc_err:
        hint = (" — Search Console 사용자 및 권한에 서비스 계정 이메일이 추가됐는지 확인"
                if "403" in gsc_err or "permission" in gsc_err.lower() else "")
        out.append(_alert("warning", "Search Console 연결 오류", gsc_err[:160] + hint))
    elif gsc_data.get("at") and not gsc_data.get("queries"):
        out.append(_alert("info", "Search Console 연결됨 · 검색 데이터 쌓이는 중",
                          "아직 검색 노출이 적어 검색어가 없습니다 (데이터는 2~3일 늦게 확정)"))
    elif not gsc_data.get("at"):
        out.append(_alert("info", "Search Console 미연결", "연결하면 실제 검색어로 키워드·제안이 좋아집니다 (gsc.py 안내)"))

    # 6-2) 다른 사이트(HQ) 상태 점검 결과
    try:
        import sites
        for sid, info in sites.SITES.items():
            if sid == sites.DEFAULT_SITE:
                continue
            h = sites.last_health(sid)
            for prob in h.get("problems") or []:
                level = "error" if "접속" in prob or "응답" in prob and "링크" not in prob else "warning"
                out.append(_alert(level, f"{info['name']}: {prob}", "사이트 선택 → 해당 사이트 화면에서 확인", key=f"{sid}:{prob}"))
    except Exception:
        pass

    # 7) 직접 등록한 기한
    for r in cfg.get("reminders") or []:
        try:
            d = (date.fromisoformat(r["date"]) - today).days
        except (KeyError, ValueError, TypeError):
            continue
        level = "error" if d <= 3 else "warning" if d <= 14 else "info"
        out.append(_alert(level, f"{r.get('title', '기한')} {dday(d)}", f"{r['date']} · {r.get('note', '')}".strip(" ·"),
                          d, "rem:" + r.get("title", "")))

    return sorted(out, key=lambda a: (LEVEL_ORDER[a["level"]], a["days"] if a["days"] is not None else 9999))
