"""
금융감독원 API 키 종류 자동 확인 — FinLife(금융상품 한눈에) / OpenDART(전자공시)
- 키 값은 GitHub Secrets(FSS_API_KEY)에서만 읽고, 결과에는 서비스 이름·상태만 남긴다 (키 값 기록 금지)
- 결과: memory/fss.json, 텔레그램이 연결돼 있으면 한 번 알림
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

import core

STATE = core.ROOT / "memory" / "fss.json"


def _finlife(key: str) -> tuple[str, str]:
    try:
        r = requests.get("https://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json", timeout=20,
                         params={"auth": key, "topFinGrpNo": "020000", "pageNo": 1})
        res = (r.json().get("result") or {})
    except (requests.RequestException, ValueError) as e:
        return "unreachable", type(e).__name__
    code = str(res.get("err_cd", ""))
    return ("ok" if code == "000" else "invalid"), f"{code} {res.get('err_msg', '')}".strip()


def _opendart(key: str) -> tuple[str, str]:
    try:
        d = requests.get("https://opendart.fss.or.kr/api/company.json", timeout=20,
                         params={"crtfc_key": key, "corp_code": "00126380"}).json()
    except (requests.RequestException, ValueError) as e:
        return "unreachable", type(e).__name__
    code = str(d.get("status", ""))
    return ("ok" if code == "000" else "invalid"), f"{code} {d.get('message', '')}".strip()


def detect(key: str | None = None) -> dict:
    key = (key if key is not None else os.getenv("FSS_API_KEY", "")).strip()
    if not key:
        return {"service": None, "note": "FSS_API_KEY 없음"}
    fin, dart = _finlife(key), _opendart(key)
    service = "finlife" if fin[0] == "ok" else "opendart" if dart[0] == "ok" else None
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "service": service,
            "finlife": {"status": fin[0], "detail": fin[1]}, "opendart": {"status": dart[0], "detail": dart[1]},
            "key_len": len(key)}  # 길이만 (값은 절대 저장하지 않음)


def run_once() -> dict:
    """아직 확인 전이거나 실패했으면 확인하고 텔레그램으로 알림. 확인되면 다시 하지 않음."""
    st = core._load_json(STATE, {})
    if st.get("service"):
        return st
    res = detect()
    if res.get("service") is None and "FSS_API_KEY 없음" in res.get("note", ""):
        return res
    core._save_json(STATE, res)
    try:
        import notify
        if notify.enabled():
            name = {"finlife": "FinLife (금융상품 한눈에) — 예금·적금·연금저축 금리", "opendart": "OpenDART (전자공시)"}
            notify.send("🔑 <b>금융감독원 키 확인</b>\n" + (f"이 키는 <b>{name[res['service']]}</b> 키입니다."
                        if res["service"] else
                        f"두 서비스 모두 통과하지 못했습니다.\nFinLife: {notify.esc(res['finlife'])}\n"
                        f"OpenDART: {notify.esc(res['opendart'])}"))
    except Exception:
        pass
    return res


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False))
