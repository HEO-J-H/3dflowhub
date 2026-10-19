"""
3dflowhub 자기 개선 루프 — 4대 에이전트
=======================================
Coder → Reviewer → Security&QA → Judge  (최대 3회 반복, 리뷰에는 git diff 만 전달)

  Coder    : TODO.md 의 `(agent)` 항목 + memory.json 교훈을 읽고 search/replace 패치 작성
  Reviewer : git diff 만 보고 버그·가독성·알고리즘 비평
  QA       : pytest 실행 + 정적 보안 점검(위험 함수, 하드코딩 비밀값, 보호 파일 수정)
  Judge    : 리뷰·QA 결과를 종합해 승인/재작업 판정 → 승인 시 브랜치·PR 생성 후 자동 머지,
             memory.json / TODO.md 갱신

실행: python agents.py                     (이 저장소, GitHub Actions: self_improve.yml)
      python agents.py --target pix2poly    (다른 저장소 — 그 저장소에 쓸 수 있는 토큰 PIX2POLY_TOKEN 필요)
필요 환경변수: LLM_API_KEY, GITHUB_TOKEN(PR/머지), GITHUB_REPOSITORY

다른 저장소(target)는 위험도로 나눈다: 바뀐 파일이 모두 auto_merge 경로(테스트·문서·화면)면 테스트 통과 후 자동 머지,
그 밖(파이프라인 코드·의존성)은 PR 만 올리고 사람이 GitHub 에서 머지 — 현황판에 '승인 대기 PR' 로 보인다.
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
# AI 관리자 제안(분류별)을 처리할 때 추가로 열어 주는 파일 — 에이전트·워크플로·growth(안전장치)는 계속 보호
CATEGORY_FILES = {"콘텐츠": {"guides.py", "evolve.py"}, "수집": {"core.py"}, "사이트·UX": {"build_site.py"},
                  "검색(SEO)": {"build_site.py"}, "운영·비용": {"manager.py"}, "수익": {"monetize.py", "build_site.py"},
                  "현황판": {"app.py"}}
PROPOSAL_TAG = re.compile(r"\[(p-[0-9a-f]{10})\|([^\]]+)\]")


def files_for(task: str) -> set[str]:
    """작업별 수정 가능 파일: 관리자 제안이면 그 분류의 파일 + 테스트, 아니면 기본 EDITABLE."""
    if TARGET:  # 다른 저장소: 과제 글에 나온 파일(경로·이름) + 테스트, 없으면 기본 파일
        named = {f for f in EDITABLE if f in task or Path(f).stem in task}
        return (named or set(TARGET["default_files"])) | set(TARGET["always"])
    m = PROPOSAL_TAG.search(task)
    if not m:
        return set(EDITABLE)
    return CATEGORY_FILES.get(m.group(2), {"core.py"}) | {"tests/test_agent_tasks.py"}


def queue_manager_tasks() -> list[str]:
    """수락됐지만 자동 실행 행동이 없는 AI 관리자 제안(이 저장소 몫)을 코딩 에이전트 할 일로 등록 (한 번만)."""
    import manager
    text = TODO.read_text(encoding="utf-8")
    added = []
    for p in manager.manual_todo(SITE):
        if p["id"] in text:
            continue
        what = re.sub(r"\s+", " ", f"{p['title']}: {p.get('proposal', '')}")[:220]
        added.append(f"- [ ] (agent) [{p['id']}|{p.get('category') or '운영·비용'}] {what}")
    if added:
        TODO.write_text(text.rstrip("\n") + "\n" + "\n".join(added) + "\n", encoding="utf-8")
    return added


def report_to_manager(task: str, ok: bool, msg: str) -> None:
    """처리 결과를 현황판 제안에 남김: 머지되면 '완료', 실패면 사람이 볼 수 있게 사유 기록(제안은 남겨 둠)."""
    m = PROPOSAL_TAG.search(task)
    if not m:
        return
    import manager
    if ok:
        manager.decide(m.group(1), "done", f"코딩 에이전트 처리: {msg}")
    else:
        manager._append({"at": manager._now(), "kind": "applied", "id": m.group(1),
                         "result": f"코딩 에이전트 보류 — 직접 처리 필요: {msg[:200]}"})
# 다른 저장소도 같은 엔진으로 — configure_target() 이 아래 전역 값을 바꿔 끼운다
TARGETS = {
    "pix2poly": {
        "repo": "HEO-J-H/Pix2Poly", "token_env": "PIX2POLY_TOKEN", "todo": ".agent/TODO.md",
        "allowed": ("backend/app/", "backend/tests/", "backend/static/", "docs/", "README.md"),
        "auto_merge": ("backend/tests/", "docs/", "backend/static/", "README.md", ".agent/"),
        "always": ("backend/tests/test_core.py",), "default_files": ("backend/app/main.py",),
        "install": ("pip", "install", "-q", "-r", "backend/requirements.txt", "pytest"),
        "test_cmd": ("python", "-m", "pytest", "-q", "backend/tests"),
        "plan": "Pix2Poly - a local FastAPI tool that turns images/URLs/videos into 3D meshes (OBJ/GLB/FBX) and PBR "
                "textures (heightfield mesh on CPU by default, optional TripoSR GPU, COLMAP for video). Goal: reliability "
                "of the CPU default path, input validation, clear errors in the web UI, tests. GPU/external tools are "
                "optional and must never be required by tests.",
    },
}
SITE = "3dflowhub"
TEST_CMD: tuple = ("python", "-m", "pytest", "-q", "tests")
AUTO_MERGE: tuple | None = None   # None = 이 저장소(테스트 통과 시 전부 자동 머지)
TOKEN_ENV = "GITHUB_TOKEN"
TARGET: dict = {}


def configure_target(name: str) -> None:
    """다른 저장소를 _targets/<name> 에 받아 작업 대상으로 지정 (토큰 없으면 RuntimeError)."""
    global ROOT, TODO, EDITABLE, GH_API, SITE, TEST_CMD, AUTO_MERGE, TOKEN_ENV, TARGET
    cfg = TARGETS[name]
    token = os.getenv(cfg["token_env"])
    if not token:
        raise RuntimeError(f"{cfg['token_env']} 없음 — {cfg['repo']} 에 쓸 수 있는 토큰을 GitHub Secrets 에 등록하세요")
    root = Path(__file__).parent / "_targets" / name
    if not (root / ".git").exists():
        root.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "clone", "-q", f"https://x-access-token:{token}@github.com/{cfg['repo']}.git", str(root)],
                       check=True, capture_output=True)
    for k, v in (("user.name", "3dflowhub-bot"), ("user.email", "41898282+github-actions[bot]@users.noreply.github.com")):
        subprocess.run(["git", "config", k, v], cwd=root, check=False)
    ROOT, SITE, TARGET = root, name, cfg
    TODO = root / cfg["todo"]
    if not TODO.exists():
        TODO.parent.mkdir(parents=True, exist_ok=True)
        TODO.write_text("# 코딩 에이전트 할 일 (3dflowhub 본사 엔진이 처리)\n\n"
                        "`- [ ] (agent)` 항목을 위에서부터 처리합니다. 사람이 직접 적어도 됩니다.\n", encoding="utf-8")
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    EDITABLE = {f for f in tracked if f.startswith(cfg["allowed"]) and f.endswith((".py", ".html", ".md", ".css", ".js"))}
    GH_API = f"https://api.github.com/repos/{cfg['repo']}"
    TEST_CMD, AUTO_MERGE, TOKEN_ENV = cfg["test_cmd"], cfg["auto_merge"], cfg["token_env"]
    subprocess.run(list(cfg["install"]), cwd=root, check=False, capture_output=True)


DANGEROUS = re.compile(r"\b(eval|exec|os\.system|subprocess|pickle\.loads|__import__|shell=True)\b")
SECRET = re.compile(r"(ntn_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|AQ\.[A-Za-z0-9_-]{30,}|ghp_[A-Za-z0-9]{30,})")
GH_API = f"https://api.github.com/repos/{os.getenv('GITHUB_REPOSITORY', 'HEO-J-H/3dflowhub')}"


def sh(*cmd: str, check: bool = True) -> str:
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True, encoding="utf-8").stdout


def ask_json(role: str, prompt: str, max_tokens: int = 4000) -> dict:
    try:
        return core._parse_json(core.llm(prompt, system=role + core.playbook("dev_team"), max_tokens=max_tokens,
                                         json_mode=True))
    except ValueError:  # 깨진 JSON → 빈 응답으로 처리하고 다음 회차에서 재시도
        return {}


CRLF = "\r\n"
EDIT_BLOCK = re.compile(r"<<<FILE (\S+)\n<<<SEARCH\n(.*?)\n={3,}\n(.*?)\n>{3,}END", re.S)


def parse_edits(text: str) -> list[dict]:
    text = text.replace(CRLF, "\n")
    return [{"file": f, "search": a, "replace": b} for f, a, b in EDIT_BLOCK.findall(text)]


def reset_files(files: set[str]) -> None:
    """추적 중인 파일은 되돌리고, 이번 작업이 새로 만든 파일은 지운다."""
    tracked = set(sh("git", "ls-files", "--", *sorted(files), check=False).split())
    sh("git", "reset", "-q", "--", *sorted(files), check=False)
    sh("git", "checkout", "--", *sorted(tracked), check=False) if tracked else None
    for f in files - tracked:
        (ROOT / f).unlink(missing_ok=True)


# ─────────────────────────── 작업 선택 ───────────────────────────
def next_task() -> str | None:
    """AI 관리자 제안(사람이 수락한 일)을 먼저, 그다음 에이전트 스스로 만든 과제."""
    tasks = [l[len("- [ ] (agent)"):].strip() for l in TODO.read_text(encoding="utf-8").splitlines()
             if l.startswith("- [ ] (agent)")]
    return next((t for t in tasks if PROPOSAL_TAG.search(t)), tasks[0] if tasks else None)


def propose_tasks(max_tasks: int = 3) -> list[str]:
    """할 일이 없으면 성찰 기록(교훈·오류·전략 이력)을 바탕으로 다음 개선 과제를 스스로 만든다."""
    mem, strategy = core.load_memory(), core.load_strategy()
    done = [re.sub(r"^- \[[x ]\] \(agent(:보류)?\) ", "", l) for l in TODO.read_text(encoding="utf-8").splitlines()
            if l.startswith("- [x] (agent)") or l.startswith("- [ ] (agent:보류)")]
    prompt = (
        "" + (f"You are the planning agent of a self-improving repo: {TARGET['plan']}\n" if TARGET else
           "You are the planning agent of a self-improving Python repo (news curation → Notion → Tistory).\n"
           "Business goal: grow policy-compliant AdSense revenue on Tistory = more search traffic (SEO titles, "
           "depth, FAQ, internal links, specific categories) x better RPM. Never add ad-click inducement.\n")
        + f"Editable files: {sorted(EDITABLE)}\n"
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
    editable = files_for(task)
    files = "\n\n".join(f"### {f}\n```python\n{(ROOT / f).read_text(encoding='utf-8') if (ROOT / f).exists() else '# (new file)'}\n```"
                        for f in sorted(editable))
    prompt = (
        f"TASK: {task}\n\nLessons from previous runs: {mem.get('lessons', [])[-5:]}\n"
        f"Reviewer/Judge feedback from last iteration: {feedback or 'none'}\n\n{files}\n\n"
        "Output ONLY edit blocks in this exact format (no JSON, no markdown fences):\n"
        "<<<FILE path/to/file.py\n<<<SEARCH\nexact existing lines\n===\nreplacement lines\n>>>END\n\n"
        "SEARCH must match the file exactly (including indentation) and occur exactly once. "
        f"Only edit these files: {sorted(editable)}. For a new file use an empty SEARCH block. "
        "Keep changes minimal; add or update a pytest test."
    )
    text = core.llm(prompt, system="You are the Coder agent, a careful senior Python engineer."
                    + core.playbook("dev_team", *([f"site_{SITE}"] if TARGET else [])), max_tokens=6000)
    return parse_edits(text)


def apply_edits(edits: list[dict], editable: set[str] | None = None) -> list[str]:
    editable = editable or EDITABLE
    problems = []
    for e in edits:
        f = e.get("file", "")
        if f not in editable:
            problems.append(f"수정 불가 파일: {f}")
            continue
        path = ROOT / f
        if not path.exists() and not e.get("search", "").strip():  # 새 파일(테스트) 생성
            path.write_text(e.get("replace", ""), encoding="utf-8", newline="\n")
            continue
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
    tests = subprocess.run(list(TEST_CMD), cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
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
def open_and_merge_pr(task: str, body: str, editable: set[str] | None = None) -> tuple[bool, str]:
    """코드 + TODO 만 담은 브랜치로 PR 생성·자동 머지. 어떤 경우에도 main 으로 돌아온다.
    (memory/ 는 PR 에 넣지 않음 → 수집 워크플로의 잦은 memory 커밋과 충돌하지 않음)"""
    token = os.getenv(TOKEN_ENV)
    branch = f"agent/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    try:
        sh("git", "checkout", "-b", branch)
        sh("git", "add", *sorted(f for f in (editable or EDITABLE) if (ROOT / f).exists()), str(TODO.relative_to(ROOT)))
        changed = sh("git", "diff", "--cached", "--name-only").split()
        sh("git", "commit", "-m", f"agent: {task[:60]}")
        if not token:
            return True, f"(로컬 실행) 브랜치 {branch} 에 커밋만 생성"
        sh("git", "push", "origin", branch)
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        pr = requests.post(f"{GH_API}/pulls", headers=h, timeout=30,
                           json={"title": f"agent: {task[:60]}", "head": branch, "base": "main", "body": body}).json()
        if "number" not in pr:
            return False, f"PR 생성 실패: {str(pr)[:200]}"
        if needs_approval(changed):
            requests.post(f"{GH_API}/issues/{pr['number']}/labels", headers=h, timeout=30,
                          json={"labels": ["agent", "needs-approval"]})
            return False, f"PR #{pr['number']} 승인 대기 (핵심 코드 변경 — GitHub 에서 확인 후 머지): {pr.get('html_url', '')}"
        m = requests.put(f"{GH_API}/pulls/{pr['number']}/merge", headers=h, timeout=30,
                         json={"merge_method": "squash"})
        if m.ok:
            requests.delete(f"{GH_API}/git/refs/heads/{branch}", headers=h, timeout=30)  # 브랜치 정리
        return m.ok, f"PR #{pr['number']} {'머지 완료' if m.ok else '머지 실패: ' + m.text[:200]}"
    except subprocess.CalledProcessError as e:
        return False, f"git 실패: {(e.stderr or e.stdout or '')[:200]}"
    finally:
        sh("git", "checkout", "-f", "main", check=False)


def needs_approval(changed: list[str]) -> bool:
    """다른 저장소에서 자동 머지 경로(테스트·문서·화면) 밖을 바꿨으면 사람 승인 필요. 이 저장소는 항상 False."""
    return AUTO_MERGE is not None and not all(f.startswith(AUTO_MERGE) for f in changed)


def record_target_run(task: str, result: str, msg: str) -> None:
    """다른 저장소 작업 결과를 본사 memory/sites/<site>/agent_runs.json 에 남김 (현황판 표시용)."""
    path = Path(__file__).parent / "memory" / "sites" / SITE / "agent_runs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = core._load_json(path, [])
    runs.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "task": task[:200],
                 "result": result, "msg": msg[:300]})
    core._save_json(path, runs[-50:])


# ─────────────────────────── 메인 루프 ───────────────────────────
def main() -> None:
    queued = queue_manager_tasks()
    if queued:
        print("AI 관리자 제안 등록:", queued)
    task = next_task()
    if not task:  # 자율 성장: 할 일이 바닥나면 다음 과제를 스스로 계획
        print("새 과제 계획:", propose_tasks())
        task = next_task()
    if not task:
        print("TODO.md 에 (agent) 작업이 없습니다.")
        return
    print(f"작업: {task}")
    editable = files_for(task)
    feedback, log, verdict = "", [], {"approve": False, "feedback": ""}
    for i in range(1, MAX_ITERATIONS + 1):
        reset_files(editable)  # 매 회차 깨끗한 상태에서 시작
        problems = apply_edits(coder(task, feedback), editable)
        sh("git", "add", "-N", *sorted(f for f in editable if (ROOT / f).exists()), check=False)  # 새 파일도 diff 에
        diff = sh("git", "diff", "--", *sorted(editable))
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
        merged, msg = open_and_merge_pr(task, "\n".join(["4-에이전트 자동 작업", "", *log]), editable)
        print(msg)
    reset_files(editable)
    sh("git", "checkout", "--", str(TODO.relative_to(ROOT)), check=False)
    pending = "승인 대기" in msg
    if pending:  # 핵심 코드 PR — 사람이 머지할 때까지 같은 과제를 다시 하지 않음
        TODO.write_text(TODO.read_text(encoding="utf-8").replace(
            f"- [ ] (agent) {task}", f"- [ ] (agent:승인대기) {task} — {msg[:120]}", 1), encoding="utf-8")
    elif not merged:  # 반려·PR 실패 → main 에서 보류 표시 (같은 작업 무한 반복 방지)
        mark_task(task, False, msg or (log[-1] if log else "실패"))
        print("보류 처리:\n" + "\n".join(log))
    if TARGET:  # 다른 저장소: TODO 표시 변경을 그 저장소 main 에 바로 반영, 본사에 결과 기록
        sh("git", "pull", "-q", "--rebase", "origin", "main", check=False)
        sh("git", "add", str(TODO.relative_to(ROOT)), check=False)
        sh("git", "commit", "-q", "-m", "chore(agent): 과제 상태 [skip ci]", check=False)
        sh("git", "push", "-q", "origin", "HEAD:main", check=False)
        record_target_run(task, "merged" if merged else "pending" if pending else "held", msg or (log[-1] if log else ""))
    report_to_manager(task, merged, msg or (log[-1] if log else "실패"))
    mem = core.load_memory()  # 교훈은 main 의 memory 에 기록 (워크플로 마지막 단계가 커밋)
    mem["lessons"] = (mem.get("lessons", []) + [f"{datetime.now():%Y-%m-%d} [{task[:40]}] {lesson}"])[-20:]
    core._save_json(core.MEMORY_PATH, mem)


if __name__ == "__main__":
    import sys
    if "--target" in sys.argv:
        try:
            configure_target(sys.argv[sys.argv.index("--target") + 1])
        except RuntimeError as ex:
            print("건너뜀:", ex)
            raise SystemExit(0)
    # 하루 실행당 처리할 과제 수 (LLM 한도와 성장 속도의 균형, 환경변수로 조절)
    for n in range(int(os.getenv("AGENT_TASKS_PER_RUN", "2"))):
        print(f"── 과제 {n + 1} ──")
        try:
            main()
        except core.LLMBudgetExceeded as ex:
            print("LLM 한도 도달 — 다음 실행에서 계속:", ex)
            break
