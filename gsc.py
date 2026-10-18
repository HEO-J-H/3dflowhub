"""Google Search Console 연동 (선택) — 사이트가 실제로 어떤 검색어로 노출·클릭되는지 가져와
키워드 생성·전략 성찰에 넣는다. GitHub Secret GSC_SERVICE_ACCOUNT(서비스 계정 JSON 전체)가 있을 때만 동작.

설정 (한 번만):
  1) Google Cloud 콘솔 → 프로젝트 → 'Google Search Console API' 사용 설정
  2) IAM → 서비스 계정 만들기 → 키(JSON) 다운로드
  3) Search Console → 설정 → 사용자 및 권한 → 서비스 계정 이메일(client_email)을 '제한됨' 권한으로 추가
  4) GitHub 저장소 → Settings → Secrets → GSC_SERVICE_ACCOUNT 에 JSON 내용 붙여넣기
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from urllib.parse import quote

import core

SITE_URL = os.getenv("GSC_SITE_URL", "https://heo-j-h.github.io/3dflowhub/")
GSC_PATH = core.ROOT / "memory" / "search_console.json"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def enabled() -> bool:
    return bool(os.getenv("GSC_SERVICE_ACCOUNT", "").strip())


def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    info = json.loads(os.environ["GSC_SERVICE_ACCOUNT"])
    return AuthorizedSession(service_account.Credentials.from_service_account_info(info, scopes=[SCOPE]))


def _query(sess, dimension: str, days: int, limit: int) -> list[dict]:
    end = date.today() - timedelta(days=2)  # 검색 데이터는 2~3일 늦게 확정
    body = {"startDate": str(end - timedelta(days=days)), "endDate": str(end),
            "dimensions": [dimension], "rowLimit": limit}
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{quote(SITE_URL, safe='')}/searchAnalytics/query"
    r = sess.post(url, json=body, timeout=30)
    r.raise_for_status()
    return [{"key": row["keys"][0], "clicks": row.get("clicks", 0), "impressions": row.get("impressions", 0),
             "ctr": round(row.get("ctr", 0), 4), "position": round(row.get("position", 0), 1)}
            for row in r.json().get("rows", [])]


def collect(days: int = 28) -> dict | None:
    """검색어·페이지별 노출/클릭을 memory/search_console.json 에 저장. 미설정이면 None."""
    if not enabled():
        return None
    sess = _session()
    data = {"at": core.datetime.now(core.timezone.utc).isoformat(), "days": days,
            "queries": _query(sess, "query", days, 100), "pages": _query(sess, "page", days, 100)}
    core._save_json(GSC_PATH, data)
    core.log.info("Search Console: 검색어 %d개, 페이지 %d개", len(data["queries"]), len(data["pages"]))
    return data


def top_queries(n: int = 15) -> list[str]:
    """노출이 많은 검색어 (키워드 생성 힌트용). 데이터가 없으면 []."""
    rows = core._load_json(GSC_PATH, {}).get("queries", [])
    return [r["key"] for r in sorted(rows, key=lambda r: -r["impressions"])[:n]]


def opportunities(n: int = 10) -> list[dict]:
    """노출은 많은데 클릭률이 낮은 검색어 (순위 8~20위) — 이 주제로 더 좋은 글을 쓰면 유입이 늘 여지가 큼."""
    rows = core._load_json(GSC_PATH, {}).get("queries", [])
    cands = [r for r in rows if r["impressions"] >= 10 and 8 <= r["position"] <= 20]
    return sorted(cands, key=lambda r: -r["impressions"])[:n]
