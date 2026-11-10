"""🛰️ AI 3D 레이더 (/radar/) — 지금 뜨는 3D 관련 AI 모델·데모·오픈소스·데이터셋 (사장님 요청 2026-11-10: 허깅페이스·시비타이·캐글·깃허브).

출처 (모두 공개 API, 로그인 없음):
  · Hugging Face 모델 — image-to-3d·text-to-3d 등 3D 작업 태그, 최근 인기순(trendingScore)
  · Hugging Face Spaces — 브라우저에서 바로 써 보는 3D 데모 (실행 중인 것만)
  · GitHub — gaussian-splatting·3d-reconstruction·blender-addon 등 주제, 최근 활동 + 별 순
  · Civitai — 3D 스타일·텍스처·게임 에셋 이미지 모델 (성인물·실존 인물 제외)
  · Kaggle — 3D 데이터셋 (인기순)
아티스트가 판단할 것만: 이름·한 줄 한국어 설명·인기(좋아요·별·내려받기)·라이선스(상업 사용 가능?)·링크·그림.
한국어 설명은 하루 한 번 AI 한 번에 묶어서 (실패하면 원문 설명). evolve 가 12시간마다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

import core

PATH = core.ROOT / "content" / "radar.json"
UA = {"User-Agent": "3dflowhub-radar/1.0 (+https://heo-j-h.github.io/3dflowhub/)"}
HF_TASKS = ["image-to-3d", "text-to-3d"]
GH_TOPICS = ["gaussian-splatting", "3d-reconstruction", "nerf", "text-to-3d", "image-to-3d", "blender-addon", "photogrammetry"]
CIVITAI_TAGS = ["3d", "game asset", "isometric", "low poly"]  # texture 태그엔 인쇄 질감 등 3D 와 무관한 것이 섞임
# 상업 사용이 대체로 가능한 라이선스 (표시용 — 최종 확인은 원문)
COMMERCIAL_OK = {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "cc0-1.0", "cc-by-4.0", "openrail", "creativeml-openrail-m",
                 "openrail++", "mpl-2.0", "isc", "unlicense", "zlib", "cc-by-sa-4.0"}


def _get(url: str, **kw):
    try:
        r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=25, **kw)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def _lic(x: str) -> dict:
    x = (x or "").lower().strip()
    return {"license": x or "확인 필요", "commercial": "가능" if x in COMMERCIAL_OK else ("불가" if "nc" in x or "non-commercial" in x
                                                                                       or "research" in x else "확인 필요")}


def hf_models(per: int = 12) -> list[dict]:
    out = []
    for task in HF_TASKS:
        for m in _get(f"https://huggingface.co/api/models?pipeline_tag={task}&sort=trendingScore&limit={per}&full=true") or []:
            mid = m.get("id", "")
            lic = next((t.split(":", 1)[1] for t in m.get("tags") or [] if t.startswith("license:")), "")
            out.append({"id": "hf-" + mid, "kind": "AI 모델", "source": "Hugging Face", "name": mid.split("/")[-1], "owner": mid.split("/")[0],
                        "url": f"https://huggingface.co/{mid}", "desc_en": task.replace("-", " "),
                        "image": f"https://cdn-thumbnails.huggingface.co/social-thumbnails/models/{mid}.png",
                        "likes": m.get("likes", 0), "downloads": m.get("downloads", 0), "task": task,
                        "updated": str(m.get("lastModified") or m.get("createdAt") or "")[:10], **_lic(lic)})
    return out


def hf_spaces(n: int = 16) -> list[dict]:
    out = []
    for s in _get(f"https://huggingface.co/api/spaces?search=3d&sort=trendingScore&limit={n * 2}&full=true") or []:
        stage = (s.get("runtime") or {}).get("stage", "")
        if stage and stage not in ("RUNNING", "RUNNING_BUILDING"):
            continue  # 꺼진 데모는 눌러도 안 됨
        sid = s.get("id", "")
        card = s.get("cardData") or {}
        out.append({"id": "hfs-" + sid, "kind": "바로 써 보기", "source": "Hugging Face Spaces", "name": card.get("title") or sid.split("/")[-1],
                    "owner": sid.split("/")[0], "url": f"https://huggingface.co/spaces/{sid}",
                    "desc_en": card.get("short_description") or "", "emoji": card.get("emoji") or "🧊",
                    "image": f"https://cdn-thumbnails.huggingface.co/social-thumbnails/spaces/{sid}.png",
                    "likes": s.get("likes", 0), "updated": str(s.get("lastModified") or "")[:10], **_lic(card.get("license", ""))})
        if len(out) >= n:
            break
    return out


def github(per: int = 6) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
    tok = __import__("os").getenv("GITHUB_TOKEN", "")
    hdr = {"Authorization": f"Bearer {tok}"} if tok else {}
    out, seen = [], set()
    for t in GH_TOPICS:
        d = _get(f"https://api.github.com/search/repositories?q=topic:{t}+pushed:>{since}&sort=stars&per_page={per}", headers=hdr) or {}
        for r in d.get("items") or []:
            if r["full_name"] in seen or r.get("archived"):
                continue
            seen.add(r["full_name"])
            out.append({"id": "gh-" + r["full_name"], "kind": "오픈소스", "source": "GitHub", "name": r["name"], "owner": r["owner"]["login"],
                        "url": r["html_url"], "desc_en": r.get("description") or "", "topic": t,
                        "image": f"https://opengraph.githubassets.com/1/{r['full_name']}",
                        "stars": r.get("stargazers_count", 0), "updated": str(r.get("pushed_at") or "")[:10],
                        **_lic((r.get("license") or {}).get("spdx_id", ""))})
    return out


def civitai(per: int = 6) -> list[dict]:
    out, seen = [], set()
    for tag in CIVITAI_TAGS:
        d = _get(f"https://civitai.com/api/v1/models?tag={requests.utils.quote(tag)}&sort=Most%20Downloaded&period=Month&nsfw=false&limit={per * 2}") or {}
        for m in d.get("items") or []:
            # 성인물·실존 인물(POI)·인물 닮은꼴은 싣지 않음
            if m.get("nsfw") or m.get("poi") or (m.get("nsfwLevel") or 1) > 1 or m.get("id") in seen:
                continue
            ver = (m.get("modelVersions") or [{}])[0]
            img = next((i.get("url") for i in ver.get("images") or [] if (i.get("nsfwLevel") or 1) <= 1 and i.get("type", "image") == "image"), "")
            tags = " ".join(m.get("tags") or []).lower() + " " + (m.get("name") or "").lower()
            if not img or not re.search(r"3d|isometric|low ?poly|game asset|diorama|voxel|clay|render", tags):
                continue
            seen.add(m["id"])
            out.append({"id": f"cv-{m['id']}", "kind": "이미지 모델", "source": "Civitai", "name": m.get("name", "")[:60],
                        "owner": (m.get("creator") or {}).get("username", ""), "url": f"https://civitai.com/models/{m['id']}",
                        "desc_en": f"{m.get('type', '')} · {', '.join((m.get('tags') or [])[:4])}", "image": img,
                        "downloads": (m.get("stats") or {}).get("downloadCount", 0), "likes": (m.get("stats") or {}).get("thumbsUpCount", 0),
                        "updated": str(ver.get("publishedAt") or "")[:10],
                        "license": "Civitai 모델별", "commercial": "가능" if m.get("allowCommercialUse") in (["Sell"], "Sell")
                        or "Sell" in (m.get("allowCommercialUse") or []) else "확인 필요"})
            if len([x for x in out if x["desc_en"].endswith(tag)]) >= per:
                break
    return out


KAGGLE_OK = re.compile(r"mesh|point ?cloud|shapenet|modelnet|3d (model|object|shape|scan|asset)|photogramm|lidar|nerf|gaussian|texture|pbr|character|furniture")
KAGGLE_NO = re.compile(r"rsna|medical|liver|brain|ct scan|mri|tumor|lung|covid|mnist|microscop|battery")


def kaggle(n: int = 10) -> list[dict]:
    out = []
    for q in ("3d", "point cloud", "mesh"):
        for d in _get(f"https://www.kaggle.com/api/v1/datasets/list?search={requests.utils.quote(q)}&sortBy=hottest") or []:
            ref = d.get("refNullable") or d.get("ref") or ""
            text = f'{d.get("titleNullable") or ""} {d.get("subtitleNullable") or ""}'.lower()
            if not ref or any(x["id"] == "kg-" + ref for x in out) or not KAGGLE_OK.search(text) or KAGGLE_NO.search(text):
                continue  # 의료 영상(3D CT 등)·숫자 손글씨처럼 3D 작업과 무관한 것 제외
            out.append({"id": "kg-" + ref, "kind": "데이터셋", "source": "Kaggle", "name": d.get("titleNullable") or ref,
                        "owner": d.get("creatorNameNullable") or "", "url": d.get("urlNullable") or f"https://www.kaggle.com/datasets/{ref}",
                        "desc_en": d.get("subtitleNullable") or "", "image": "",
                        "downloads": d.get("downloadCount") or 0, "likes": d.get("voteCount") or 0,
                        "updated": str(d.get("lastUpdated") or "")[:10], **_lic(d.get("licenseNameNullable") or "")})
            if len(out) >= n:
                return out
    return out


def _korean(items: list[dict], old: dict) -> None:
    """한 줄 한국어 설명 — 새 항목만 AI 한 번에 묶어서. 실패하면 영어 설명 그대로."""
    todo = [x for x in items if x["id"] not in old or not old[x["id"]].get("desc")]
    for x in items:
        if x["id"] in old and old[x["id"]].get("desc"):
            x["desc"] = old[x["id"]]["desc"]
    todo = todo[:120]
    if not todo or not core.background_ok(2):
        return
    lines = "\n".join(f'{i}. [{x["kind"]}] {x["name"]} — {x["desc_en"][:160]}' for i, x in enumerate(todo))
    try:
        out = core._parse_json(core.llm(
            "For each numbered item write ONE short Korean line (max 50 chars) telling a 3D artist what it does or what they "
            "can do with it. Use only the given text; if unclear, describe the category plainly. Keep product names in English.\n"
            f"{lines}\nReturn JSON {{\"0\": \"...\", \"1\": \"...\"}}.", system="You are a concise Korean tech editor.",
            max_tokens=5000, json_mode=True))
    except core.LLMBudgetExceeded:
        return
    except Exception:  # noqa: BLE001
        return
    for i, x in enumerate(todo):
        v = str(out.get(str(i)) or "").strip()
        if v:
            x["desc"] = core.fix_terms(v)[:80]


def refresh() -> dict:
    old = {x["id"]: x for x in core._load_json(PATH, [])}
    got, errors = [], []
    for name, fn in (("HF 모델", hf_models), ("HF 데모", hf_spaces), ("GitHub", github), ("Civitai", civitai), ("Kaggle", kaggle)):
        try:
            got += fn()
        except Exception as e:  # noqa: BLE001 — 출처 하나가 막혀도 나머지는 계속
            errors.append(f"{name}: {str(e)[:80]}")
    if not got:
        return {"items": len(old), "errors": errors}
    _korean(got, old)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for x in got:
        x["seen_at"] = now
        x["first_seen"] = (old.get(x["id"]) or {}).get("first_seen") or now
    core._save_json(PATH, got)
    return {"items": len(got), "new": sum(1 for x in got if x["id"] not in old), "errors": errors}


def load() -> list[dict]:
    return core._load_json(PATH, [])


if __name__ == "__main__":
    print(refresh())
