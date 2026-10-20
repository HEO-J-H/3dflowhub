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
MAX_ITERATIONS = 4
CODE_TEMP = 0.15   # 코드·리뷰·판정은 낮은 온도 (반복성)
EDITABLE = {"core.py", "app.py", "evolve.py", "tests/test_core.py"}  # 에이전트가 수정 가능한 파일 (워크플로/에이전트 자신은 보호)
# AI 관리자 제안(분류별)을 처리할 때 추가로 열어 주는 파일 — 에이전트·워크플로·growth(안전장치)는 계속 보호
CATEGORY_FILES = {"콘텐츠": {"guides.py", "evolve.py"}, "수집": {"core.py"}, "사이트·UX": {"build_site.py"},
                  "검색(SEO)": {"build_site.py"}, "운영·비용": {"manager.py"}, "수익": {"monetize.py", "build_site.py"},
                  "현황판": {"app.py"}}
PROPOSAL_TAG = re.compile(r"\[(p-[0-9a-f]{10})\|([^\]]+)\]")


GUIDE_TAG = re.compile(r"\[guide:([\w-]+)\]")
GUIDE_DIR = "docs/agent-guides"


def guide_for(task: str) -> tuple[str, str]:
    """과제의 [guide:이름] → (경로, 내용). 다른 저장소(target)에서만, 없으면 ("", "")."""
    m = GUIDE_TAG.search(task)
    if not (TARGET and m):
        return "", ""
    rel = f"{GUIDE_DIR}/{m.group(1)}.md"
    path = ROOT / rel
    return (rel, path.read_text(encoding="utf-8")) if path.exists() else ("", "")


def append_guide_lesson(task: str, result: str, lesson: str) -> str:
    """가이드 맨 아래 '진행 기록·배운 점'에 한 줄 추가 — 가이드가 작업할수록 자란다. 바꾼 파일 경로 반환."""
    rel, text = guide_for(task)
    if not rel or not lesson.strip():
        return ""
    head = re.sub(r"\s+", " ", GUIDE_TAG.sub("", task)).strip()[:60]
    line = f"- {datetime.now():%Y-%m-%d} [{result}] {head}: {re.sub(r'\s+', ' ', lesson).strip()[:200]}"
    (ROOT / rel).write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
    return rel


def files_for(task: str) -> set[str]:
    """작업별 수정 가능 파일: 관리자 제안이면 그 분류의 파일 + 테스트, 아니면 기본 EDITABLE."""
    if TARGET:  # 다른 저장소: 과제 글에 나온 파일(경로·이름) + 테스트, 없으면 기본 파일
        named = {f for f in EDITABLE if f in task or Path(f).stem in task}
        new = {p for p in re.findall(r"[\w./-]+\.(?:py|md|html|js|css)", task)
               if p.startswith(TARGET["allowed"]) and ".." not in p}
        return (named | new or set(TARGET["default_files"])) | set(TARGET["always"])
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
        "allowed": ("backend/app/", "backend/tests/", "backend/static/", "web/", "docs/", "README.md"),
        "auto_merge": ("backend/tests/", "docs/", "backend/static/", "README.md", ".agent/"),  # web/ 은 공개 페이지라 승인
        "always": ("backend/tests/test_core.py",), "default_files": ("backend/app/main.py",),
        "install": ("pip", "install", "-q", "-r", "backend/requirements.txt", "pytest"),
        "test_cmd": ("python", "-m", "pytest", "-q", "backend/tests"),
        "plan": "Pix2Poly - a public browser tool (web/: JS port of the heightfield mesh + PBR maps, GitHub Pages) plus a local FastAPI tool that turns images/URLs/videos into 3D meshes (OBJ/GLB/FBX) and PBR "
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
                                         json_mode=True, temperature=CODE_TEMP))
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
    # 가이드가 있는 과제(사람이 설계를 정해 둔 단계) → 사람이 수락한 제안 → 에이전트가 스스로 만든 과제
    return next((t for t in tasks if GUIDE_TAG.search(t)),
                next((t for t in tasks if PROPOSAL_TAG.search(t)), tasks[0] if tasks else None))


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
    _g_rel, guide = guide_for(task)
    prompt = (
        f"REPOSITORY MAP (file: top-level functions/classes):\n{repo_map()}\n\n" +
        (f"DESIGN GUIDE ({_g_rel}) — follow it exactly, including its '하지 말 것' and the progress log:\n{guide[:7000]}\n\n"
         if guide else "")
        + f"TASK: {task}\n\nLessons from previous runs: {mem.get('lessons', [])[-5:]}\n"
        f"Reviewer/Judge feedback from last iteration: {feedback or 'none'}\n\n{files}\n\n"
        "Output ONLY edit blocks in this exact format (no JSON, no markdown fences):\n"
        "<<<FILE path/to/file.py\n<<<SEARCH\nexact existing lines\n===\nreplacement lines\n>>>END\n\n"
        "SEARCH must match the file exactly (including indentation) and occur exactly once. "
        f"Only edit these files: {sorted(editable)}. For a new file use an empty SEARCH block. "
        "Keep changes minimal; add or update a pytest test."
    )
    text = core.llm(prompt, system="You are the Coder agent, a careful senior Python engineer."
                    + core.playbook("dev_team", *([f"site_{SITE}"] if TARGET else [])), max_tokens=6000,
                    temperature=CODE_TEMP)
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


def failure_summary(qa_result: dict) -> str:
    """pytest 출력에서 실패 테스트 이름과 오류 줄만 뽑기 (경고·진행 표시는 버림)."""
    out = qa_result.get("test_output", "")
    keep = [l.strip() for l in out.splitlines()
            if l.startswith(("FAILED", "ERROR", "E ")) or re.match(r"^\s*E\s{2,}", l) or "Error:" in l]
    tail = out.strip().splitlines()
    head = " / ".join(dict.fromkeys(keep))[:700] or (tail[-1][:300] if tail else "출력 없음")
    sec = f" 보안: {qa_result['security']}" if qa_result.get("security") else ""
    return f"테스트 실패 — {head}{sec}"


def repo_map(limit: int = 4000) -> str:
    """편집 가능한 Python 파일의 최상위 함수·클래스 이름 목록."""
    import ast as _ast
    lines = []
    for f in sorted(EDITABLE):
        if not f.endswith(".py") or not (ROOT / f).exists():
            continue
        try:
            tree = _ast.parse((ROOT / f).read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names = [n.name for n in tree.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))]
        lines.append(f"{f}: {', '.join(names[:25])}")
    return "\n".join(lines)[:limit]


def retry_held() -> bool:
    """'(agent:보류)' 과제 하나를 '(재시도)' 표시와 함께 다시 열기 — 한 과제당 한 번만 (무한 반복 방지)."""
    text = TODO.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("- [ ] (agent:보류) ") and "(재시도)" not in line:
            body = line[len("- [ ] (agent:보류) "):].split(" — ")[0]
            TODO.write_text(text.replace(line, f"- [ ] (agent) {body} (재시도)", 1), encoding="utf-8")
            return True
    return False


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


# ─────────────────────────── 사람의 PR 결정 반영 (현황판 → GitHub) ───────────────────────────
DECISIONS = {"approve": "승인(머지)", "reject": "거절(닫기)", "revise": "수정 요청"}


def decisions_path(site: str) -> Path:
    return Path(__file__).parent / "memory" / "sites" / site / "pr_decisions.json"


def record_decision(site: str, number: int, v: str, note: str = "") -> None:
    """현황판에서 누른 결정을 기록만 한다 (현황판에는 GitHub 쓰기 토큰이 없음 — 실제 처리는 apply_pr_decisions)."""
    assert v in DECISIONS
    path = decisions_path(site)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = core._load_json(path, [])
    items.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "pr": int(number), "v": v,
                  "note": note.strip()[:500], "done": None})
    core._save_json(path, items[-100:])


def apply_pr_decisions(site: str) -> list[str]:
    """기록된 결정을 GitHub 에 반영: 승인 → 스쿼시 머지(충돌이면 에이전트에 다시 맡김), 거절 → 닫기,
    수정 요청 → 메모를 새 과제로 등록하고 PR 닫기. 10분 수집 워크플로가 호출 (AI 사용 없음)."""
    cfg = TARGETS[site]
    token = os.getenv(cfg["token_env"])
    path = decisions_path(site)
    items = core._load_json(path, [])
    todo_ = [x for x in items if not x.get("done")]
    if not token or not todo_:
        return []
    api = f"https://api.github.com/repos/{cfg['repo']}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    def comment(n: int, text: str) -> None:
        requests.post(f"{api}/issues/{n}/comments", headers=h, timeout=30, json={"body": text})

    def close(n: int) -> bool:
        return requests.patch(f"{api}/pulls/{n}", headers=h, timeout=30, json={"state": "closed"}).ok

    def requeue(n: int, title: str, note: str) -> None:
        r = requests.get(f"{api}/contents/{cfg['todo']}", headers=h, timeout=30)
        if not r.ok:
            return
        import base64
        cur = r.json()
        text = base64.b64decode(cur["content"]).decode("utf-8").rstrip("\n")
        if re.search(rf"^- \[ \] \(agent\)[^\n]*PR #{n}\b", text, re.M):
            return  # 사람이 이미 이 PR 을 대체하는 과제(가이드 단계 등)를 적어 둠
        task = PROPOSAL_TAG.sub("", re.sub(r"^agent:\s*", "", title)).strip()
        text += f"\n- [ ] (agent) PR #{n} 다시 하기 — {task[:120]} · 사람 요청: {note[:200]}\n"
        requests.put(f"{api}/contents/{cfg['todo']}", headers=h, timeout=30, json={
            "message": f"chore(agent): PR #{n} 수정 요청을 과제로 [skip ci]", "sha": cur["sha"],
            "content": base64.b64encode(text.encode("utf-8")).decode()})

    done = []
    for x in todo_:
        n = x["pr"]
        pr = requests.get(f"{api}/pulls/{n}", headers=h, timeout=30).json()
        if pr.get("state") != "open":
            x["done"], x["result"] = datetime.now(timezone.utc).isoformat(timespec="seconds"), "이미 닫힌 PR"
            continue
        if x["v"] == "approve":
            m = requests.put(f"{api}/pulls/{n}/merge", headers=h, timeout=30, json={"merge_method": "squash"})
            if m.ok:
                requests.delete(f"{api}/git/refs/heads/{pr['head']['ref']}", headers=h, timeout=30)
                result = "머지 완료"
            else:  # 충돌 등 — 에이전트가 최신 main 에서 다시 만들도록
                comment(n, f"사람이 승인했지만 머지할 수 없어 닫고 에이전트에 다시 맡깁니다: {m.text[:200]}")
                requeue(n, pr.get("title", ""), "승인됨 — 최신 main 기준으로 같은 변경을 다시 만들기")
                close(n)
                result = "머지 불가(충돌) → 다시 작업 과제로"
        elif x["v"] == "reject":
            comment(n, "사람이 거절했습니다" + (f": {x['note']}" if x.get("note") else "."))
            result = "닫음" if close(n) else "닫기 실패"
        else:
            comment(n, f"수정 요청: {x.get('note') or '(메모 없음)'} — 이 PR 은 닫고 새 과제로 다시 만듭니다.")
            requeue(n, pr.get("title", ""), x.get("note") or "")
            close(n)
            result = "수정 요청 → 새 과제"
        x["done"], x["result"] = datetime.now(timezone.utc).isoformat(timespec="seconds"), result
        done.append(f"PR #{n} {DECISIONS[x['v']]}: {result}")
    core._save_json(path, items)
    return done


# ─────────────────────────── 메인 루프 ───────────────────────────
def main() -> None:
    queued = queue_manager_tasks()
    if queued:
        print("AI 관리자 제안 등록:", queued)
    task = next_task()
    if not task and retry_held():  # 보류 과제는 쌓인 교훈을 가지고 한 번 더
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
        qa_result = qa(diff)
        if not qa_result["tests_passed"] or qa_result["security"]:
            verdict = {"approve": False, "feedback": failure_summary(qa_result)}
            log.append(f"[{i}] tests={qa_result['tests_passed']} security={qa_result['security']} — 리뷰 생략")
            print(log[-1])
            feedback = verdict["feedback"]
            continue
        review = reviewer(diff)
        verdict = judge(task, review, qa_result)
        log.append(f"[{i}] review={review.get('verdict')} tests={qa_result['tests_passed']} "
                   f"security={qa_result['security']} approve={verdict['approve']}")
        print(log[-1])
        if verdict["approve"]:
            break
        feedback = f"review issues: {review.get('issues')} / judge: {verdict['feedback']}"

    lesson = verdict.get("lesson") or (verdict["feedback"][:200] if verdict["feedback"] else "")
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
    if not TARGET:
        record_target_run(task, "merged" if merged else "held", msg or (log[-1] if log else ""))
    if TARGET:  # 다른 저장소: TODO 표시 변경을 그 저장소 main 에 바로 반영, 본사에 결과 기록
        sh("git", "pull", "-q", "--rebase", "origin", "main", check=False)
        g_rel = append_guide_lesson(task, "완료" if merged else "승인대기" if pending else "보류",
                                    lesson or (log[-1] if log else ""))
        if g_rel:
            sh("git", "add", g_rel, check=False)
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
    if "--apply-decisions" in sys.argv:  # 10분 워크플로: 사람의 PR 결정만 반영하고 끝 (AI 사용 없음)
        done_ = apply_pr_decisions(sys.argv[sys.argv.index("--apply-decisions") + 1])
        print(done_)
        if any("과제" in d for d in done_):  # 수정 요청·충돌 재작업 → 다음 예약을 기다리지 않고 바로
            print("::notice::RUN_AGENTS_NOW")
            if os.getenv("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                    fh.write("run_agents=1\n")
        raise SystemExit(0)
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
