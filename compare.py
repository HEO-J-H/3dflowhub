"""주제별 툴 비교 (/compare/) — 같은 작업(최적화·UV·베이크·리깅·내보내기 …)을 툴마다 어디서·어떻게 하는지 한 장에.

다른 사이트는 툴 하나씩만 설명한다. 3dflowhub 는 '이 작업을 Blender·Max·Maya·Houdini·Unreal 에서 각각' 비교하고,
상황별 추천·툴 사이 넘기기(파이프라인) 팁·응용까지 묶는다 → 툴을 바꾸거나 여러 툴을 쓰는 실무자가 검색해 들어오는 페이지.
근거: 사이트에 이미 있는 기초 가이드·오류 해결(rag 검색) — 서로 어긋나지 않게. 저장: content/compare/*.json, 하루 상한.
"""
from __future__ import annotations

from datetime import datetime, timezone

import core

DIR = core.ROOT / "content" / "compare"
DAILY_MAX = 4
TOOLS = ["Blender", "3ds Max", "Maya", "Houdini", "Unreal Engine"]

# (slug, 한국어 제목, 비교할 작업 설명(영어, AI 지시용), 추가로 비교할 툴)
TOPICS: list[tuple[str, str, str, list[str]]] = [
    ("poly-reduction", "폴리곤 줄이기·최적화 (Decimate·ProOptimizer·Reduce)", "polygon reduction / mesh optimization and LOD creation", []),
    ("lod", "LOD 만들기", "creating LODs for real-time / game engines", []),
    ("retopology", "리토폴로지", "retopology of high-poly / scanned meshes", ["ZBrush"]),
    ("uv-unwrap", "UV 펴기", "UV unwrapping, seams, packing", []),
    ("texture-bake", "텍스처 베이크 (노멀·AO)", "baking normal / ambient occlusion maps from high to low poly", ["Substance 3D"]),
    ("pbr-material", "PBR 머티리얼 만들기", "building a PBR material (base color, roughness, metallic, normal)", ["Substance 3D"]),
    ("hard-surface", "하드서페이스 모델링 (베벨·불리언)", "hard-surface modeling with bevel and boolean workflows", []),
    ("sculpting", "스컬핑 기본", "digital sculpting basics (brushes, dynamic topology / remesh)", ["ZBrush"]),
    ("rigging", "캐릭터 리깅 기본", "basic character rigging: skeleton, skinning / weight painting", []),
    ("keyframe-animation", "키프레임 애니메이션·그래프 에디터", "keyframe animation and curve / graph editing", []),
    ("particles-vfx", "파티클·VFX", "particle systems and VFX (sparks, smoke, debris)", []),
    ("cloth-sim", "천 시뮬레이션", "cloth simulation setup", []),
    ("fluid-smoke", "연기·불·유체 시뮬레이션", "smoke, fire and fluid simulation", []),
    ("fbx-export", "FBX 내보내기 (게임 엔진용)", "exporting FBX for game engines: scale, axis, smoothing, animation", []),
    ("gltf-usd", "glTF·USD 내보내기·가져오기", "glTF and USD export / import", ["NVIDIA Omniverse"]),
    ("import-cleanup", "가져온 모델 정리 (스케일·노멀·중복 점)", "cleaning up imported models: scale, normals, merged vertices", []),
    ("lighting", "조명 기본 (3점 조명·HDRI)", "lighting basics: three-point lighting and HDRI", []),
    ("render-settings", "렌더 설정·노이즈 줄이기", "render settings and noise reduction / denoising", []),
    ("instancing", "인스턴싱·스캐터 (대량 배치)", "instancing and scattering many objects", []),
    ("scripting", "스크립트로 반복 작업 자동화", "automating repetitive tasks with scripting (Python / MAXScript / VEX / Blueprint)", []),
]


def load_all() -> list[dict]:
    if not DIR.exists():
        return []
    return [x for x in (core._load_json(f, None) for f in sorted(DIR.glob("*.json"))) if isinstance(x, dict)]


def pending() -> list[tuple]:
    have = {f.stem for f in DIR.glob("*.json")} if DIR.exists() else set()
    return [t for t in TOPICS if t[0] not in have]


def make(slug: str, title: str, task: str, extra: list[str]) -> dict | None:
    tools = TOOLS + extra
    try:
        from guides import _site_context
        site = _site_context(f"{title} {task} " + " ".join(tools))
    except Exception:  # noqa: BLE001
        site = ""
    prompt = (site + f"Write a Korean comparison page: how to do this task in each tool — {task}.\n"
              f"Tools: {', '.join(tools)}.\n"
              "Use only well-established facts; keep official English menu / node / modifier names. If a tool has no "
              "native way, say so (and name the common plugin only if well known). Never invent version numbers.\n"
              "Return JSON:\n"
              ' "summary": 2 Korean sentences — what this task is and why the tools differ,\n'
              ' "rows": one per tool {"tool", "where": exact menu / modifier / node name, "how": 1-2 Korean sentences, '
              '"strength": Korean short phrase, "limit": Korean short phrase},\n'
              ' "pick": 3-4 {"case": Korean situation, "tool": tool name, "why": Korean reason},\n'
              ' "handoff": 2-4 Korean tips for moving this work between tools (export settings, scale, axis, naming),\n'
              ' "apply": 3 Korean ideas to apply / combine this in real projects,\n'
              ' "pitfalls": 2-4 Korean common mistakes → fix')
    try:
        data = core._parse_json(core.llm(prompt, system="You are a senior 3D technical director who uses every major DCC "
                                         "daily, writing precise Korean comparison pages." + core.playbook("common", limit=2000),
                                         max_tokens=2600, json_mode=True))
    except core.LLMBudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        core.log.warning("툴 비교 생성 실패 %s: %s", slug, e)
        return None
    rows = [r for r in data.get("rows") or [] if isinstance(r, dict) and r.get("tool") and r.get("where")]
    if len(rows) < 3 or not data.get("summary"):  # 비교가 안 되는 응답은 올리지 않음
        return None
    return {"id": slug, "title": title, "task": task, "summary": str(data["summary"]), "rows": rows,
            "pick": [p for p in data.get("pick") or [] if isinstance(p, dict) and p.get("case")],
            "handoff": [str(x) for x in data.get("handoff") or []], "apply": [str(x) for x in data.get("apply") or []],
            "pitfalls": [str(x) for x in data.get("pitfalls") or []],
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def write(max_new: int = 2) -> list[str]:
    """아직 없는 비교 페이지를 조금씩 (하루 상한)."""
    if not core.background_ok(max_new):
        return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    left = DAILY_MAX - sum(1 for x in load_all() if x.get("at", "").startswith(today))
    done = []
    for t in pending()[:max(0, min(max_new, left))]:
        try:
            x = make(*t)
        except core.LLMBudgetExceeded:
            break
        if x:
            core._save_json(DIR / f"{x['id']}.json", x)
            done.append(x["title"])
    return done
