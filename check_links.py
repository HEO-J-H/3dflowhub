"""빌드된 사이트(_site)의 내부 링크 점검 — 깨진 링크가 있으면 실패(배포 전 단계에서 사용).
사용: python check_links.py  (build_site.py 다음에 실행)"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).parent / "_site"
BASE = "https://example.invalid/3dflowhub/"


def broken_links() -> dict[str, str]:
    bad: dict[str, str] = {}
    for f in ROOT.rglob("*.html"):
        rel = f.relative_to(ROOT).as_posix()
        for href in re.findall(r'href="([^"#?]+)', f.read_text(encoding="utf-8")):
            if "${" in href or href.startswith(("http", "mailto:", "javascript:", "data:")):
                continue  # 외부 링크·JS 템플릿 제외
            path = urlparse(urljoin(BASE + rel, href)).path
            if not path.startswith("/3dflowhub/"):
                bad.setdefault(path, rel)
                continue
            target = ROOT / unquote(path[len("/3dflowhub/"):])
            if path.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                bad.setdefault(path, rel)
    return bad


if __name__ == "__main__":
    bad = broken_links()
    for link, page in list(bad.items())[:30]:
        print(f"깨진 링크: {link}  ← {page}")
    print(f"내부 링크 점검: 깨진 링크 {len(bad)}개")
    sys.exit(1 if bad else 0)
