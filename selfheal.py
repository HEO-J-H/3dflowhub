"""AI 관리자 자가 복구 — 사람(또는 Claude)이 끼지 않아도 고장을 알아채고 고치거나, 사람 몫만 정확히 남긴다.

1) record_tests() / heal(): 단위 테스트가 깨졌거나 수집이 멈췄으면, 마지막 정상 시점 이후 머지된
   에이전트 커밋(agent: …)을 하나씩 되돌려 테스트가 다시 통과하는지 확인하고 바로 push.
2) probe(): 사이트 기능을 실제로 호출(뉴스레터 구독 주소 등) → 고장은 제안으로 등록 (같은 고장은 한 번만).
3) triage(): '직접 작업'(수락됐지만 자동 행동 없는 제안)을 분류 — 이미 반영·중복·논의는 스스로 완료,
   사람만 할 수 있는 일(키·계정·외부 게시)은 무엇을 어디서 할지 적어 남김.
기록: memory/selfheal.json (현황판 알림·텔레그램이 읽음)
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

import core

LOG_PATH = core.ROOT / "memory" / "selfheal.json"
TESTS_PATH = core.ROOT / "memory" / "tests_status.json"
STALL_MIN = 60          # 수집 기록이 이보다 오래 없으면 '멈춤'
TRIAGE_MAX = 4          # 한 번에 분류할 직접 작업 수 (AI 한도 절약)
UA = {"User-Agent": "Mozilla/5.0 (3dflowhub health check)"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def log(kind: str, text: str, ok: bool = True) -> None:
    items = core._load_json(LOG_PATH, [])
    items.append({"at": _iso(_now()), "kind": kind, "ok": ok, "text": text[:400]})
    core._save_json(LOG_PATH, items[-100:])


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=core.ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# ─────────────────────────── 1) 테스트 실패·수집 멈춤 → 자동 되돌림 ───────────────────────────
def record_tests(rc: int, log_file: str = "pytest.log") -> dict:
    """워크플로 단위 테스트 결과 기록. ok_at = 마지막으로 테스트가 통과한 시각 (되돌릴 범위 기준)."""
    prev = core._load_json(TESTS_PATH, {})
    try:
        tail = open(log_file, encoding="utf-8", errors="ignore").read()[-800:]
    except OSError:
        tail = ""
    now = _iso(_now())
    st = {"at": now, "ok": rc == 0, "tail": tail, "ok_at": now if rc == 0 else prev.get("ok_at", "")}
    core._save_json(TESTS_PATH, st)
    return st


def last_run_at() -> datetime | None:
    runs = core.load_memory().get("runs", [])
    return _parse(runs[-1]["at"]) if runs and runs[-1].get("at") else None


def diagnose(now: datetime | None = None) -> tuple[str, datetime | None]:
    """('tests'|'stall'|'', 되돌릴 범위의 시작 시각)."""
    now = now or _now()
    ts = core._load_json(TESTS_PATH, {})
    if ts and not ts.get("ok"):
        return "tests", _parse(ts.get("ok_at", "")) or (now - timedelta(days=1))
    last = last_run_at()
    if last and now - last > timedelta(minutes=STALL_MIN):
        return "stall", last
    return "", None


def agent_commits(since: datetime) -> list[tuple[str, str]]:
    """since(30분 여유) 이후 main 에 들어온 에이전트 커밋 [(sha, 제목)] 최신순."""
    out = git("log", f"--since={_iso(since - timedelta(minutes=30))}", "--format=%H\t%s", "--grep=^agent: ").stdout
    return [tuple(l.split("\t", 1)) for l in out.splitlines() if "\t" in l]


def tests_pass() -> bool:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=core.ROOT,
                          capture_output=True).returncode == 0


def _hold_task(subject: str, why: str) -> None:
    """되돌린 에이전트 작업은 TODO 에서 보류로 돌려 같은 실수를 곧바로 반복하지 않게."""
    todo = core.ROOT / "TODO.md"
    key = subject.removeprefix("agent: ").split(" (#")[0][:60]
    lines = todo.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines):
        if l.startswith("- [x] (agent) ") and key[:40] in l:
            lines[i] = l.replace("- [x] (agent) ", "- [ ] (agent:보류) ", 1) + f" — {why}"
            todo.write_text("\n".join(lines) + "\n", encoding="utf-8")
            git("add", "TODO.md")
            git("commit", "-q", "--amend", "--no-edit")
            return


def heal() -> str:
    """고장 원인이 최근 에이전트 커밋이면 되돌리고 push. 사람 손 없이 수집이 다시 돌게 하는 게 목표."""
    why, since = diagnose()
    if not why:
        return ""
    commits = agent_commits(since)
    if not commits:
        msg = f"{'테스트 실패' if why == 'tests' else '수집 멈춤'} — 최근 에이전트 변경이 없어 자동 되돌림 대상 없음 (원인 확인 필요)"
        log("heal", msg, ok=False)
        return msg
    reverted = []
    for sha, subject in commits:
        files = git("show", "--name-only", "--format=", sha).stdout.split()
        if any(f.startswith(".github/") for f in files):  # 워크플로 파일은 봇 토큰으로 push 불가
            continue
        if git("revert", "--no-edit", sha).returncode != 0:
            git("revert", "--abort")
            continue
        _hold_task(subject, "테스트를 깨뜨려 자가 복구가 되돌림")
        reverted.append(subject[:80])
        if tests_pass():
            break
    if not reverted:
        log("heal", "되돌릴 수 있는 에이전트 커밋이 없음", ok=False)
        return ""
    fixed = tests_pass()
    for attempt in range(3):
        if git("pull", "-q", "--rebase", "origin", "main").returncode == 0 and \
                git("push", "-q", "origin", "HEAD:main").returncode == 0:
            break
    msg = f"{'테스트 실패' if why == 'tests' else '수집 멈춤'} → 에이전트 변경 {len(reverted)}건 자동 되돌림" \
          f"({'; '.join(reverted)}) — 테스트 {'통과' if fixed else '여전히 실패'}"
    log("heal", msg, ok=fixed)
    return msg


# ─────────────────────────── 2) 사이트 기능 실동작 점검 ───────────────────────────
def probe() -> list[dict]:
    """설정된 외부 기능이 실제로 동작하는지 호출해 본다. [{'key','title','how'}] 고장 목록."""
    cfg = core._load_json(core.ROOT / "config.json", {})
    issues = []
    user = (cfg.get("newsletter_buttondown") or "").strip()
    if user:
        try:
            code = requests.get(f"https://buttondown.com/{user}", headers=UA, timeout=15).status_code
        except requests.RequestException:
            code = None
        if code == 404:
            issues.append({"key": f"buttondown:{user}", "title": "뉴스레터 구독 칸이 '찾을 수 없음'으로 실패",
                           "how": f"Buttondown 계정 '{user}' 공개 페이지가 없음(404). buttondown.com 로그인 → Settings → "
                                  "Basics 의 Username 을 확인하고, 가입 확인 메일 인증 → 현황판 설정 ③ 뉴스레터 칸에 그 이름 입력"})
    return issues


def report_issues(issues: list[dict]) -> list[str]:
    """고장을 제안판에 '사람 할 일'로 등록 (같은 key 는 열려 있는 동안 한 번만)."""
    import hashlib

    import manager
    seen = {p.get("probe_key") for p in manager.board()["proposals"] if p["status"] in ("new", "accepted", "held")}
    evs = []
    for it in issues:
        if it["key"] in seen:
            continue
        now = manager._now()
        evs.append({"at": now, "kind": "proposal", "id": "p-" + hashlib.md5(f"{now}{it['key']}".encode()).hexdigest()[:10],
                    "title": it["title"][:80], "category": "운영·비용", "evidence": "자가 점검: 실제 호출 실패",
                    "proposal": it["how"][:900], "expected": "기능 복구", "effort": "낮음", "action": None,
                    "risk": "낮음", "probe_key": it["key"], "site": "3dflowhub"})
        evs.append({"at": now, "kind": "decision", "id": evs[-1]["id"], "v": "accepted",
                    "note": "자가 점검이 등록 — 사람만 할 수 있는 일 (계정 설정)"})
    if evs:
        manager._append(*evs)
        for e in evs[::2]:
            log("probe", e["title"], ok=False)
    return [e["title"] for e in evs[::2]]


# ─────────────────────────── 3) 직접 작업 자동 분류 ───────────────────────────
VERDICTS = ("done_already", "duplicate", "discussion", "agent", "human")


def _context_for(site: str) -> str:
    import manager
    done = [p["title"] for p in manager.board()["proposals"]
            if (p.get("site") or "3dflowhub") == site and p["status"] == "done"][:30]
    commits = git("log", "-40", "--format=%s").stdout.splitlines() if site == "3dflowhub" else []
    if site != "3dflowhub":
        import sites
        try:
            r = requests.get(f"https://api.github.com/repos/{sites.SITES[site]['repo']}/commits?per_page=30", timeout=15)
            commits = [c["commit"]["message"].splitlines()[0] for c in r.json()] if r.ok else []
        except (requests.RequestException, KeyError, ValueError):
            commits = []
    return f"이미 끝낸 제안: {done}\n최근 커밋: {[c for c in commits if 'chore(memory)' not in c][:30]}"


def classify(p: dict, ctx: str) -> dict:
    import agents
    prompt = (f"사이트 '{p.get('site') or '3dflowhub'}' 의 수락된 할 일을 분류하라.\n제목: {p['title']}\n"
              f"내용: {p.get('proposal', '')}\n근거: {p.get('evidence', '')}\n{ctx}\n"
              "verdict 하나: done_already(최근 커밋/끝낸 제안으로 이미 반영됨), duplicate(끝낸 제안과 같은 일), "
              "discussion(결정·모니터링뿐이라 따로 할 일 없음), agent(코드 수정으로 해결 가능), "
              "human(키 발급·계정 설정·외부 사이트 게시처럼 사람 로그인이 꼭 필요). 확실하지 않으면 human 또는 agent.\n"
              'JSON {"verdict": "...", "reason": "한 문장", "how": "human 이면 사람이 어디서 무엇을 할지 단계별, 아니면 빈 문자열"}')
    d = agents.ask_json("You are a precise operations manager. Answer in Korean.", prompt, 500)
    return d if d.get("verdict") in VERDICTS else {}


def triage(limit: int = TRIAGE_MAX) -> list[str]:
    import manager
    if not core.background_ok(limit):
        return []
    triaged = {e.get("id") for e in manager._events() if e.get("kind") == "triage"}
    todo = [p for p in manager.manual_todo() if p["id"] not in triaged][:limit]
    out, ctx_cache = [], {}
    for p in todo:
        site = p.get("site") or "3dflowhub"
        ctx = ctx_cache.setdefault(site, _context_for(site))
        d = classify(p, ctx)
        if not d:
            continue
        v, reason = d["verdict"], str(d.get("reason", ""))[:200]
        manager._append({"at": manager._now(), "kind": "triage", "id": p["id"], "verdict": v, "reason": reason})
        if v in ("done_already", "duplicate", "discussion"):
            manager.decide(p["id"], "done", f"AI 관리자 자동 정리({v}): {reason}")
        elif v == "human":
            manager._append({"at": manager._now(), "kind": "applied", "id": p["id"],
                             "result": f"사람 할 일 — {str(d.get('how') or reason)[:400]}"})
        # agent: 코딩 에이전트가 queue_manager_tasks() 로 가져감 (에이전트 대상 저장소일 때)
        out.append(f"{p['title'][:40]} → {v}")
    if out:
        log("triage", "; ".join(out))
    return out


if __name__ == "__main__":
    if "--tests" in sys.argv:
        st = record_tests(int(sys.argv[sys.argv.index("--tests") + 1]))
        print("tests ok" if st["ok"] else "tests FAILED")
        raise SystemExit(0)
    if "--heal" in sys.argv:
        print(heal() or "정상")
        raise SystemExit(0)
    print("probe:", report_issues(probe()))
    print("triage:", triage())
