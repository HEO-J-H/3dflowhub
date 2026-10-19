"""
실무 파이프라인 레시피 — AI 3D 게시판 소식을 '내 작업 툴에 붙여 쓰는 방법 + 바로 쓰는 스크립트'로
==================================================================================================
예: 3D 생성 AI 로 만든 GLB → Blender 애드온으로 가져오기·스케일·정리 / 3ds Max 는 MAXScript 로 같은 일.

- 근거: AI 3D 게시판의 최근 글 요약 (없는 사실을 지어내지 않도록 요약만 보여줌)
- 스크립트는 각 툴의 표준 API 와 로컬 파일만 다룸 (AI 서비스의 API 호출은 만들지 않음 — 존재하지 않는 주소 환각 방지)
- 검증: Python(Blender·Maya) 은 문법 분석 + 애드온 필수 요소, MAXScript 는 괄호·따옴표 짝 검사. 실패하면 한 번 고쳐 쓰게 하고, 그래도 실패면 버림
- 생성: 6시간마다 1개 (AI 여유 50% 이상일 때만), content/recipes/*.json → build_site 가 /recipes/ 페이지로
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import core

RECIPE_DIR = core.ROOT / "content" / "recipes"
FAIL_PATH = core.ROOT / "memory" / "recipe_failures.json"  # Blender 실행 검증 실패 기록 (다음 생성 때 AI 에 알려 줌)
MAX_FAILS = 2
SOURCE_DOMAIN = "AI 3D"
# 작업 툴 → (스크립트 언어, 형식 설명)
HOSTS = {
    "Blender": ("python", "a complete Blender add-on (bl_info, Operator/Panel classes, register/unregister) using only bpy"),
    "3ds Max": ("maxscript", "a MAXScript macroScript or utility using only built-in MAXScript functions"),
    "Maya": ("python", "a Maya Python script using only maya.cmds (one main function plus a small UI window)"),
}
MIN_POSTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def recipe_id(category: str, host: str) -> str:
    return hashlib.md5(f"{category}|{host}".encode()).hexdigest()[:10]


def published(r: dict) -> bool:
    """사이트에 올릴 레시피: Blender 는 실제 실행 검증을 통과한 것만, 나머지 툴은 문법 검사 통과분."""
    return r.get("host") != "Blender" or bool((r.get("runtime") or {}).get("ok"))


def load_all() -> list[dict]:
    if not RECIPE_DIR.exists():
        return []
    return sorted((r for f in RECIPE_DIR.glob("*.json") if (r := core._load_json(f, None))),
                  key=lambda r: r.get("at", ""), reverse=True)


# ─────────────────────────── 스크립트 검증 ───────────────────────────
def check_script(lang: str, host: str, code: str) -> str:
    """문제가 없으면 "", 있으면 사유. (실행 검증이 아니라 문법·필수 요소 검사)"""
    if len(code.strip()) < 80:
        return "스크립트가 너무 짧음"
    if lang == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return f"Python 문법 오류 {e.lineno}행: {e.msg}"
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        if host == "Blender" and not ({"register", "unregister"} <= names and "bl_info" in code):
            return "Blender 애드온 필수 요소(bl_info, register, unregister) 누락"
        if re.search(r"\b(subprocess|os\.system|eval|exec|requests|urllib)\b", code):
            return "외부 실행·네트워크 호출 포함 (허용 안 함)"
        return maya_api_errors(code) if host == "Maya" else ""
    problem = maxscript_parse_errors(code)
    if problem:
        return problem
    # MAXScript: 주석·문자열을 빼고 괄호 짝 확인 (문법 분석기가 없을 때의 최소 검사이자 이중 확인)
    body = re.sub(r"--[^\n]*", "", re.sub(r'"(?:\\.|[^"\\])*"', '""', code))
    if body.count('"') % 2:
        return "따옴표 짝이 맞지 않음"
    for o, c in ("()", "[]"):
        depth = 0
        for ch in body:
            depth += (ch == o) - (ch == c)
            if depth < 0:
                return f"괄호 {o}{c} 짝이 맞지 않음"
        if depth:
            return f"괄호 {o}{c} 짝이 맞지 않음"
    if re.search(r"\b(DOSCommand|ShellLaunch|HiddenDOSCommand|python\.Execute)\b", code):
        return "외부 실행 포함 (허용 안 함)"
    return ""


MAYA_CODES = ("attr-defined", "call-arg")  # 없는 maya.cmds 함수, 없는 인자 — 스텁 오류로 인한 오탐이 적은 것만
MXS_CHECKER = core.ROOT / "tools" / "mxs" / "mxs_check.cjs"


def maya_api_errors(code: str) -> str:
    """maya-stubs + mypy: maya.cmds 에 없는 함수·인자를 찾는다 (Maya 없이). 도구가 없으면 건너뜀."""
    try:
        import mypy.api
    except ImportError:
        return ""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "recipe_maya.py"
        f.write_text(code, encoding="utf-8")
        out, _err, _rc = mypy.api.run([str(f), "--check-untyped-defs", "--ignore-missing-imports", "--no-error-summary",
                                       "--show-error-codes", "--no-incremental", "--cache-dir", os.devnull])
    bad = [ln.split(": error: ", 1)[1] for ln in out.splitlines()
           if ": error: " in ln and any(f"[{c}]" in ln for c in MAYA_CODES)]
    return ("Maya API 오류: " + " / ".join(bad[:3]))[:300] if bad else ""


def maxscript_parse_errors(code: str) -> str:
    """MAXScript 문법 분석 (HAG87/vscode-maxscript-lsp 문법, node 필요). 도구가 없으면 건너뜀."""
    node = shutil.which("node")
    if not node or not MXS_CHECKER.exists():
        return ""
    try:
        r = subprocess.run([node, str(MXS_CHECKER)], input=code, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        res = json.loads(r.stdout or "{}")
    except (subprocess.TimeoutExpired, ValueError):
        return ""
    errs = res.get("errors") or []
    return ("MAXScript 문법 오류: " + " / ".join(f"{e['line']}행 {e['msg'][:90]}" for e in errs[:3]))[:300] if errs else ""


# ─────────────────────────── Blender 실제 실행 검증 ───────────────────────────
def blender_bin() -> str | None:
    found = os.getenv("BLENDER_BIN") or shutil.which("blender")
    if found:
        return found
    for exe in sorted(Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe"), reverse=True):
        return str(exe)
    return None


# Blender 검증에서 확인할 수 있는 기대 결과 (tools/blender_check.py EXPECT 와 같은 이름)
EXPECT = {"transforms_applied": "rotation/scale applied (rotation 0, scale 1)",
          "no_loose_verts": "no vertices without edges", "no_duplicate_verts": "no overlapping duplicate vertices",
          "keeps_objects": "no mesh objects deleted", "has_material": "every mesh has a material",
          "origin_centered": "object origin moved to geometry center", "exported_file": "writes a file to the given path"}


def run_blender_check(script: str, timeout: int = 180, expect: list[str] | None = None) -> dict:
    """화면 없는 Blender 에서 애드온 등록 → 테스트 장면에 Operator 실행 → 해제 (tools/blender_check.py)."""
    exe = blender_bin()
    if not exe:
        return {"ok": None, "error": "Blender 없음"}
    with tempfile.TemporaryDirectory() as d:
        addon, out = Path(d) / "addon.py", Path(d) / "result.json"
        addon.write_text(script, encoding="utf-8")
        try:
            subprocess.run([exe, "-b", "--factory-startup", "--python", str(core.ROOT / "tools" / "blender_check.py"),
                            "--", str(addon), str(out), ",".join(expect or [])], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"{timeout}초 안에 끝나지 않음 (무한 반복 의심)"}
        return core._load_json(out, {"ok": False, "error": "검사 결과 없음 (Blender 가 비정상 종료)"})


def verify_blender(limit: int = 10) -> list[str]:
    """아직 실행 검증 안 된 Blender 레시피를 검증. 통과 → 사이트 공개, 실패 → 삭제하고 사유 기록(다음 생성 때 반영)."""
    if not blender_bin():
        return []
    fails = core._load_json(FAIL_PATH, {})
    done = []
    for r in [r for r in load_all() if r.get("host") == "Blender" and "runtime" not in r][:limit]:
        res = run_blender_check(r["script"], expect=r.get("expect"))
        path = RECIPE_DIR / f"{r['id']}.json"
        if res.get("ok") and not r.get("expect"):
            res = {"ok": False, "error": "약속한 기대 결과(expect)가 없음 — 결과를 확인할 수 없음"}
        if res.get("ok"):
            r["runtime"] = {"ok": True, "blender": res.get("blender"), "at": _now().isoformat(timespec="seconds"),
                            "steps": [s["name"] for s in res.get("steps", [])]}
            r["checked"] = (f"Blender {res.get('blender', '')} 에서 테스트 장면으로 실행 · 결과 확인 통과 "
                            f"({', '.join(r.get('expect', []))})")
            core._save_json(path, r)
            done.append(f"통과: {r['title']}")
        else:
            fails.setdefault(r["id"], []).append(str(res.get("error", ""))[-400:])
            path.unlink(missing_ok=True)
            done.append(f"실패(삭제): {r['title']} — {str(res.get('error', ''))[-120:]}")
    core._save_json(FAIL_PATH, fails)
    return done


# ─────────────────────────── 생성 ───────────────────────────
def candidates(days: int = 60) -> list[tuple[str, str, list[dict]]]:
    """(AI 3D 세부 분야, 작업 툴, 근거 글) — 글이 충분하고 아직 레시피가 없는 조합, 글 많은 순."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    hidden = {k for k, v in core.curation_state().items() if v == "hide"}
    groups: dict[str, list[dict]] = {}
    for f in core.POSTS_DIR.glob("*.json"):
        p = core._load_json(f, {})
        if (p.get("domain") == SOURCE_DOMAIN and p.get("title_ko") and f.stem not in hidden
                and (p.get("collected_at") or "") >= cutoff and p.get("category")
                and not str(p["category"]).startswith("기타")):
            groups.setdefault(p["category"], []).append({**p, "id": f.stem})
    have = {r.get("id") for r in load_all()} | {k for k, v in core._load_json(FAIL_PATH, {}).items()
                                                 if len(v) >= MAX_FAILS}  # 두 번 실패한 조합은 그만
    out = []
    for cat, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(ps) < MIN_POSTS:
            continue
        ps.sort(key=lambda p: p.get("collected_at") or "", reverse=True)
        out += [(cat, host, ps) for host in HOSTS if recipe_id(cat, host) not in have]
    return out


def make_recipe(category: str, host: str, posts: list[dict]) -> dict | None:
    lang, fmt = HOSTS[host]
    items = [{"id": p["id"], "title": p["title_ko"], "summary": (p.get("summary") or "")[:260]} for p in posts[:12]]
    prompt = (
        f"Recent Korean news summaries about '{category}' (AI 3D field):\n{json.dumps(items, ensure_ascii=False)}\n\n"
        f"Design ONE practical production pipeline that lets a {host} artist actually use this kind of AI output "
        "today (e.g. import AI-generated meshes/splats/textures, clean up, rescale, retopology prep, LOD, batch "
        "export, material setup). Use only facts from the summaries; do not invent product features or versions.\n"
        f"Write {fmt}. The script must work on LOCAL FILES only (no network, no AI service API calls, no subprocess), "
        "be safe to run on a copy of the scene, and include short English comments. Every pipeline stage you list "
        "must be something the script really does (or clearly marked as a manual step).\nReturn JSON:\n"
        ' "title": Korean title <=45 chars (e.g. "AI 생성 GLB를 Blender에서 한 번에 정리하는 애드온"),\n'
        ' "problem": 2 Korean sentences — what pain this solves in production,\n'
        ' "pipeline": 3-6 {"tool": tool/stage name, "action": Korean one-line} in order,\n'
        ' "script": the full script as a string,\n'
        ' "install": 2-4 Korean steps to install/load it,\n'
        ' "usage": 3-5 Korean steps to use it,\n'
        ' "limits": 2-3 Korean caveats (what it does not handle),\n'
        ' "sources": up to 4 ids of the summaries this is based on'
        + (',\n "expect": 1-4 outcome checks the script GUARANTEES on a test scene of selected meshes '
           '(unapplied rotation/scale, duplicate vertices, a loose vertex), chosen from '
           f'{json.dumps(EXPECT)} — they will be verified by actually running it' if host == "Blender" else "")
    )
    past = core._load_json(FAIL_PATH, {}).get(recipe_id(category, host), [])
    if past:
        prompt += ("\n\nA previous attempt FAILED when actually run in headless Blender on a test scene "
                   f"(selected meshes, object mode). Error: {past[-1]}\nAvoid that mistake.")
    system = "You are a senior technical artist / pipeline TD writing reliable tools." + core.playbook("common", limit=3000)
    feedback = ""
    for _ in range(2):  # 검증 실패 시 사유를 알려 주고 한 번 더
        try:
            out = core._parse_json(core.llm(prompt + feedback, system=system, max_tokens=3500, json_mode=True))
        except core.LLMBudgetExceeded:
            raise
        except Exception as e:
            core.log.warning("레시피 생성 실패 %s/%s: %s", category, host, e)
            return None
        if not isinstance(out, dict) or not out.get("script") or not out.get("pipeline"):
            return None
        code = str(out["script"]).replace("\r\n", "\n").strip("\n` ")
        problem = check_script(lang, host, code)
        if not problem:
            break
        feedback = f"\n\nYour previous script failed validation: {problem}. Return the full corrected JSON."
    else:
        core.log.warning("레시피 스크립트 검증 실패 %s/%s: %s", category, host, problem)
        return None
    fx = core.fix_terms
    valid = {p["id"] for p in posts}
    return {
        "id": recipe_id(category, host), "domain": SOURCE_DOMAIN, "category": category, "host": host, "lang": lang,
        "title": fx(str(out.get("title") or f"{category} → {host} 파이프라인"))[:60],
        "problem": fx(str(out.get("problem", "")))[:400],
        "pipeline": [{"tool": str(s.get("tool", ""))[:40], "action": fx(str(s.get("action", "")))[:160]}
                     for s in out["pipeline"] if isinstance(s, dict) and s.get("tool")][:6],
        "script": code[:20000],
        "install": [fx(str(x)) for x in (out.get("install") or [])][:4],
        "usage": [fx(str(x)) for x in (out.get("usage") or [])][:5],
        "limits": [fx(str(x)) for x in (out.get("limits") or [])][:3],
        "sources": [i for i in (out.get("sources") or []) if i in valid][:4] or [p["id"] for p in posts[:3]],
        "expect": [x for x in (out.get("expect") or []) if x in EXPECT][:4] if host == "Blender" else [],
        "checked": "문법 검사 통과 · 실제 툴 실행은 미검증",
        "at": _now().isoformat(timespec="seconds"),
    }


def write_recipes(max_new: int = 1, gate: bool = True) -> list[str]:
    budget = int(core.load_config().get("llm_daily_budget", 500))
    if max_new <= 0 or (gate and core.llm_budget_left() < budget * 0.5):
        return []
    done = []
    for cat, host, ps in candidates():
        if len(done) >= max_new:
            break
        try:
            r = make_recipe(cat, host, ps)
        except core.LLMBudgetExceeded:
            break
        if r:
            core._save_json(RECIPE_DIR / f"{r['id']}.json", r)
            done.append(r["title"])
    return done


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        print("\n".join(verify_blender()) or "검증할 Blender 레시피 없음")
