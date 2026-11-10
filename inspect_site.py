"""사이트 점검관 — 빌드된 _site 를 방문자처럼 훑어 '사람이 보면 바로 이상한 것'을 찾는다 (배포마다, pages.yml).

사장님이 직접 찾아냈던 버그 종류를 규칙으로 (2026-11): 화면에 날것 데이터({'step': 1 …}), None·undefined·[object Object],
깨진 글자, 논문 그림 주소 번호 중복, 사이트맵 주소 한글, 그림 없는 큰 카드, 그만둔 메뉴 이름(실무 파이프라인·검증된 스크립트)이
남은 것, 같은 제목 반복. 결과: memory/inspect.json (현황판·관리자), 심각하면 CI 경고. 새 버그를 사람이 찾으면 여기에 규칙을 더한다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "_site"
TEXT_RULES = {
    "날것 데이터가 화면에": re.compile(r"\{'(step|description|heading|body)'\s*:"),
    "None/undefined 표시": re.compile(r">\s*(None|undefined|null|NaN|\[object Object\])\s*<"),
    "깨진 글자": re.compile(r"[ÃÂ][\x80-\xbf]|�"),
    "그만둔 메뉴 이름": re.compile(r"검증된 스크립트 받아보기|>실무 파이프라인<"),
}
HTML_RULES = {
    "논문 그림 주소 번호 중복": re.compile(r"arxiv\.org/html/([\d.]+v\d+)/\1/"),
    "빈 그림 주소": re.compile(r'<img[^>]+src=""'),
}
SKIP = ("recipes/", "manual/")  # 이동용 페이지


def inspect(site: Path = SITE) -> dict:
    found: dict[str, list[str]] = {}
    for f in site.rglob("*.html"):
        rel = f.relative_to(site).as_posix()
        if rel.startswith(SKIP) or f.name.startswith("google"):
            continue
        html = f.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
        for name, rx in TEXT_RULES.items():
            if rx.search(text):
                found.setdefault(name, []).append(rel)
        for name, rx in HTML_RULES.items():
            if rx.search(html):
                found.setdefault(name, []).append(rel)
    sm = (site / "sitemap.xml").read_text(encoding="utf-8") if (site / "sitemap.xml").exists() else ""
    bad_loc = [u for u in re.findall(r"<loc>([^<]+)</loc>", sm) if re.search(r"[^\x21-\x7e]", u)]
    if bad_loc:
        found["사이트맵 주소에 한글 그대로"] = bad_loc[:20]
    titles = Counter(m for f in (site / "p").glob("*.html")
                     for m in re.findall(r"<h1[^>]*>(.*?)</h1>", f.read_text(encoding="utf-8", errors="ignore"))[:1])
    dup = [t for t, n in titles.items() if n > 1]
    if dup:
        found["같은 제목 글 여러 개"] = dup[:20]
    return {"issues": {k: {"count": len(v), "examples": v[:8]} for k, v in found.items()},
            "total": sum(len(v) for v in found.values())}


if __name__ == "__main__":
    r = inspect()
    (ROOT / "memory").mkdir(exist_ok=True)
    (ROOT / "memory" / "inspect.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in r["issues"].items():
        print(f"::warning::사이트 점검 — {k} {v['count']}곳 (예: {', '.join(v['examples'][:3])})")
    print("사이트 점검 통과" if not r["issues"] else f"사이트 점검: 문제 {r['total']}곳")
