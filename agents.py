"""
3dflowhub 자기 개선 루프 — 4대 에이전트
=======================================
Coder → Reviewer → Security&QA → Judge  (최대 3회 반복, 리뷰에는 git diff 만 전달)

  Coder    : TODO.md 의 `(agent)` 항목 + memory.json 교훈을 읽고 search/replace 패치 작성
  Reviewer : git diff 만 보고 버그·가독성·알고리즘 비평
  QA       : pytest 실행 + 정적 보안 점검(위험 함수, 하드코딩 비밀값, 보호 파일 수정)
  Judge    : 리뷰·QA 결과를 종합해 승인/재작업 판정 → 승인 시 브랜치·PR 생성 후 자동 머지,
             memory.json / TODO.md 갱신

실행: python agents.py            (GitHub Actions: self_improve.yml)
필요 환경변수: LLM_API_KEY, GITHUB_TOKEN(PR/머지), GITHUB_REPOSITORY
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

import core

ROOT = Path(__file__).parent
TODO = ROOT / "TODO.md"
MAX_ITERATIONS = 3
EDITABLE = {"core.py", "app.py", "evolve.py", "tests/test_core.py"}  # 에이전트가 수정 가능한 파일 (워크플로/에이전트 자신은 보호)
DANGEROUS = re.compile(r"\b(eval|exec|os\.system|subprocess|pickle\.loads|__import__|shell=True)\b")
SECRET = re.compile(r"(ntn_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|AQ\.[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{30,})")
GH_API = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY', 'HEO-J-H/3dflowhub')}"


def sh(*cmd: str, check: bool = True) -> str:
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True, encoding="utf-8").stdout


def ask_json(role: str, prompt: str, max_tokens: int = 4000) -> dict:
    try:
        return core._parse_json(core.llm(prompt, system=role, max_tokens=max_tokens, json_mode=True))
    except ValueError:  # 깨진 JSON → 빈 응답으로 처리하고 다음 회차에서 재시도
        return {}


CRLF = "\r\n"
EDIT_BLOCK = re.compile(r"<<<FILE (\S+)\n<<<SEARCH\n(.*?)\n={3,}\n(.*?)\n>{3,}END", re.S)


def parse_edits(text: str) -> list[dict]:
    text = text.replace(CRLF, "\n")
    return [{"file": f, "search": a, "replace": b} for f, a, b in EDIT_BLOCK.findall(text)]


# ─────────────────────────── 작업 선택 ───────────────────────────
def next_task() -> str | None:
    for line in TODO.read_text(encoding="utf-8").splitlines():
        if line.startswith("- [ ] (agent)"):
            return line[len("- [ ] (agent)"):].strip()
    return None


def propose_tasks(max_tasks: int = 3) -> list[str]:
    """할 일이 없으면 성찰 기록(교훈·오류·전략 이력)을 바탕으로 다음 개선 과제를 스스로 만든다."""
    mem, strategy = core.load_memory(), core.load_strategy()
    done = [re.sub(r"^- \[[x ]\] \(agent(:보류)?\) ", "", l) for l in TODO.read_text(encoding="utf-8").splitlines()
            if l.startswith("- [x] (agent)") or l.startswith("- [ ] (agent:보류)")]
    prompt = (
        "You are the planning agent of a self-improving Python repo (news curation → Notion → Tistory).\n"
        "Business goal: grow policy-compliant AdSense revenue on Tistory = more search traffic (SEO titles, "
        "depth, FAQ, internal links, specific categories) x better RPM. Never add ad-click inducement.\n"
        f"Editable files: {sorted(EDITABLE)}\n"
        f"Recent lessons: {mem.get('lessons', [])[-8:]}\n"
        f"Recent run errors: {[r.get('errors') for r in mem.get('runs', [])[-5:]]}\n"
        f"Strategy history: {strategy.get('history', [])[-5:]}\n"
        f"Already done or deferred (do not repeat): {done[-15:]}\n"
        f"Propose up to {max_tasks} SMALL, concrete, testable code tasks (one function each, add a pytest test). "
        "Prefer robustness, data quality, category specificity, and tests. No new dependencies, no network in tests.\n"
        'Return JSON {"tasks": ["<function>(): <what to change> 및 테스트 추가", ...]} in Korean.'
    )
    tasks = [t.strip().replace("\n", " ")[:160] for t in ask_json("You are a careful tech lead.", prompt, 800)
             .get("tasks", []) if isinstance(t, str) and t.strip()][:max_tasks]
    if tasks:
        with TODO.open("a", encoding="utf-8") as f:
            f.write("".join(f"\n- [ ] (agent) {t}" for t in tasks))
    return tasks


def mark_task(task: str, ok: bool, note: str) -> None:
    text = TODO.read_text(encoding="utf-8")
    old = f"- [ ] (agent) {task}"
    new = f"- [x] (agent) {task}" if ok else f"- [ ] (agent:보류) {task} — {note[:80]}"
    TODO.write_text(text.replace(old, new, 1), encoding="utf-8")


# ─────────────────────────── 에이전트 ───────────────────────────
def coder(task: str, feedback: str) -> list[dict]:
    mem = core.load_memory()
    files = "\n\n".join(f"### {f}\n```python\n{(ROOT / f).read_text(encoding='utf-8')}\n```" for f in sorted(EDITABLE))
    prompt = (
        f"TASK: {task}\n\nLessons from previous runs: {mem.get('lessons', [])[-5:]}\n"
        f"Reviewer/Judge feedback from last iteration: {feedback or 'none'}\n\n{files}\n\n"
        "Output ONLY edit blocks in this exact format (no JSON, no markdown fences):\n"
        "<<<FILE path/to/file.py\n<<<SEARCH\nexact existing lines\n===\nreplacement lines\n>>>END\n\n"
        "SEARCH must match the file exactly (including indentation) and occur exactly once. "
        f"Only edit these files: {sorted(EDITABLE)}. Keep changes minimal; add or update a pytest test."
    )
    text = core.llm(prompt, system="You are the Coder agent, a careful senior Python engineer.", max_tokens=6000)
    return parse_edits(text)


def apply_edits(edits: list[dict]) -> list[str]:
    problems = []
    for e in edits:
        f = e.get("file", "")
        if f not in EDITABLE:
            problems.append(f"수정 불가 파일: {f}")
            continue
        path = ROOT / f
        src = path.read_text(encoding="utf-8").replace(CRLF, "\n")
        if src.count(e.get("search", "")) != 1 or not e.get("search"):
            problems.append(f"{f}: search 블록이 정확히 1회 일치하지 않음")
            continue
        path.write_text(src.replace(e["search"], e.get("replace", ""), 1), encoding="utf-8", newline="\n")
    return problems


def reviewer(diff: str) -> dict:
    return ask_json(
        "You are the Reviewer agent. Review only the given git diff.",
        f"git diff:\n```diff\n{diff[:12000]}\n```\n"
        'Return JSON {"verdict": "approve"|"revise", "issues": ["..."]} focusing on bugs, readability, algorithms.',
        1500,
    )


def qa(diff: str) -> dict:
    tests = subprocess.run(["python", "-m", "pytest", "-q", "tests"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8")
    added = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    security = [f"위험 함수 사용: {m}" for m in set(DANGEROUS.findall(added))]
    security += ["비밀값 하드코딩 의심"] if SECRET.search(added) else []
    return {"tests_passed": tests.returncode == 0, "test_output": tests.stdout[-1500:], "security": security}


def judge(task: str, review: dict, qa_result: dict) -> dict:
    if not qa_result["tests_passed"] or qa_result["security"]:  # 테스트/보안 실패는 LLM 판단 없이 반려
        return {"approve": False, "feedback": f"tests={qa_result['test_output'][-600:]} security={qa_result['security']}"}
    out = ask_json(
        "You are the Orchestrator/Judge agent.",
        f"TASK: {task}\nReview: {json.dumps(review, ensure_ascii=False)}\nTests passed: True\n"
        'Return JSON {"approve": true|false, "feedback": "what to fix if not approved", "lesson": "one short lesson"}',
        800,
    )
    return {"approve": bool(out.get("approve")), "feedback": out.get("feedback", ""), "lesson": out.get("lesson", "")}


# ─────────────────────────── PR / 머지 ───────────────────────────
def open_and_merge_pr(task: str, body: str) -> tuple[bool, str]:
    """코드 + TODO 만 담은 브랜치로 PR 생성·자동 머지. 어떤 경우에도 main 으로 돌아온다.
    (memory/ 는 PR 에 넣지 않음 → 수집 워크플로의 잦은 memory 커밋과 충돌하지 않음)"""
    token = os.getenv("GITHUB_TOKEN")
    branch = f"agent/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    try:
        sh("git", "checkout", "-b", branch)
        sh("git", "add", *sorted(EDITABLE), "TODO.md")
        sh("git", "commit", "-m", f"agent: {task[:60]}")
        if not token:
            return True, f"(로컬 실행) 브랜치 {branch} 에 커밋만 생성"
        sh("git", "push", "origin", branch)
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        pr = requests.post(f"{GH_API}/pulls", headers=h, timeout=30,
                           json={"title": f"agent: {task[:60]}", "head": branch, "base": "main", "body": body}).json()
        if "number" not in pr:
            return False, f"PR 생성 실패: {str(pr)[:200]}"
        m = requests.put(f"{GH_API}/pulls/{pr['number']}/merge", headers=h, timeout=30,
                         json={"merge_method": "squash"})
        if m.ok:
            requests.delete(f"{GH_API}/git/refs/heads/{branch}", headers=h, timeout=30)  # 브랜치 정리
        return m.ok, f"PR #{pr['number']} {'머지 완료' if m.ok else '머지 실패: ' + m.text[:200]}"
    except subprocess.CalledProcessError as e:
        return False, f"git 실패: {(e.stderr or e.stdout or '')[:200]}"
    finally:
        sh("git", "checkout", "-f", "main", check=False)


# ─────────────────────────── 메인 루프 ───────────────────────────
def main() -> None:
    task = next_task()
    if not task:  # 자율 성장: 할 일이 바닥나면 다음 과제를 스스로 계획
        print("새 과제 계획:", propose_tasks())
        task = next_task()
    if not task:
        print("TODO.md 에 (agent) 작업이 없습니다.")
        return
    print(f"작업: {task}")
    feedback, log, verdict = "", [], {"approve": False, "feedback": ""}
    for i in range(1, MAX_ITERATIONS + 1):
        sh("git", "checkout", "--", *EDITABLE, check=False)  # 매 회차 깨끗한 상태에서 시작
        problems = apply_edits(coder(task, feedback))
        diff = sh("git", "diff", "--", *EDITABLE)
        if problems or not diff:
            feedback = f"패치 적용 실패: {problems or '변경 없음'}"
            log.append(f"[{i}] {feedback}")
            continue
        review = reviewer(diff)
        qa_result = qa(diff)
        verdict = judge(task, review, qa_result)
        log.append(f"[{i}] review={review.get('verdict')} tests={qa_result['tests_passed']} "
                   f"security={qa_result['security']} approve={verdict['approve']}")
        print(log[-1])
        if verdict["approve"]:
            break
        feedback = f"review issues: {review.get('issues')} / judge: {verdict['feedback']}"

    lesson = verdict.get("lesson") or (verdict["feedback"][:120] if verdict["feedback"] else "")
    merged, msg = False, ""
    if verdict["approve"]:
        mark_task(task, True, "")  # PR 에 완료 표시 포함 → 머지되면 main 에 반영
        merged, msg = open_and_merge_pr(task, "\n".join(["4-에이전트 자동 작업", "", *log]))
        print(msg)
    sh("git", "checkout", "--", *EDITABLE, "TODO.md", check=False)
    if not merged:  # 반려·PR 실패 → main 에서 보류 표시 (같은 작업 무한 반복 방지)
        mark_task(task, False, msg or (log[-1] if log else "실패"))
        print("보류 처리:\n" + "\n".join(log))
    mem = core.load_memory()  # 교훈은 main 의 memory 에 기록 (워크플로 마지막 단계가 커밋)
    mem["lessons"] = (mem.get("lessons", []) + [f"{datetime.now():%Y-%m-%d} [{task[:40]}] {lesson}"])[-20:]
    core._save_json(core.MEMORY_PATH, mem)


if __name__ == "__main__":
    # 하루 실행당 처리할 과제 수 (LLM 한도와 성장 속도의 균형, 환경변수로 조절)
    for n in range(int(os.getenv("AGENT_TASKS_PER_RUN", "2"))):
        print(f"── 과제 {n + 1} ──")
        try:
            main()
        except core.LLMBudgetExceeded as ex:
            print("LLM 한도 도달 — 다음 실행에서 계속:", ex)
            break
