"""3dflowhub 대시보드 — 실행: streamlit run app.py"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

import core

st.set_page_config(page_title="3dflowhub", page_icon="🧊", layout="wide")
REVENUE_CSV = Path(core.ROOT) / "memory" / "revenue.csv"
GH_REPO = os.getenv("GH_REPO", "HEO-J-H/3dflowhub")
GH_PAT = os.getenv("GH_PAT", "")  # workflow_dispatch 원격 트리거용 (repo: actions write)

# ─────────────────────────── 사이드바 ───────────────────────────
cfg = core.load_config()
with st.sidebar:
    st.header("⚙️ 수집 설정")
    interval = st.selectbox("수집 주기", list(core.INTERVALS), index=list(core.INTERVALS).index(cfg["interval"]))
    max_items = st.slider("한 번에 수집할 최대 글 수", 5, 30, int(cfg["max_items"]))
    domains = [d for d in core.DOMAINS if st.checkbox(d, value=d in cfg["domains"])]
    publish = st.toggle("티스토리 발행", value=cfg["publish"])

    st.header("✉️ 메일 알림")
    email_to = st.text_input("받는 주소", cfg["email_to"])
    email_per_day = st.number_input("하루 최대 수신 횟수", 0, 48, int(cfg["email_per_day"]))

    if st.button("💾 설정 저장", use_container_width=True):
        core.save_config({"interval": interval, "max_items": max_items, "domains": domains,
                          "publish": publish, "email_to": email_to, "email_per_day": email_per_day})
        st.success("config.json 저장됨 — 깃허브에 커밋/푸시하면 클라우드 실행에도 반영됩니다.")

    st.caption("※ '계속'은 GitHub cron 최소 간격(10분)으로 실행됩니다.")

# ─────────────────────────── 수동 실행 ───────────────────────────
st.title("🧊 3dflowhub 큐레이션 현황판")

if "job" not in st.session_state:
    st.session_state.job = {"running": False, "result": None, "error": None}
job = st.session_state.job


def _run_local(job: dict, params: dict) -> None:
    try:
        job["result"] = core.run_pipeline(**params)
    except Exception as e:
        job["error"] = str(e)
    finally:
        job["running"] = False


def _dispatch_github() -> str:
    r = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/actions/workflows/auto_curation.yml/dispatches",
        headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"max_items": str(max_items), "domains": ",".join(domains)}},
        timeout=20,
    )
    return "GitHub Actions 실행 요청 완료" if r.status_code == 204 else f"요청 실패 {r.status_code}: {r.text[:200]}"


c1, c2 = st.columns(2)
if c1.button("🚀 지금 바로 자료 수집 및 노션 업로드 실행", type="primary", disabled=job["running"],
             use_container_width=True):
    job.update(running=True, result=None, error=None)
    threading.Thread(target=_run_local, daemon=True,
                     args=(job, {"max_items": max_items, "domains": domains, "publish": publish})).start()
if c2.button("☁️ GitHub Actions로 실행", disabled=not GH_PAT, use_container_width=True):
    st.info(_dispatch_github())

if job["running"]:
    st.info("⏳ 백그라운드에서 수집 중… (새로고침하면 결과가 표시됩니다)")
elif job["result"]:
    st.success(f"완료: {job['result']}")
elif job["error"]:
    st.error(job["error"])

# ─────────────────────────── 현황판 ───────────────────────────
@st.cache_data(ttl=300)
def load_rows() -> pd.DataFrame:
    return pd.DataFrame(core.fetch_dashboard_rows())


df = load_rows()
today = datetime.now().strftime("%Y-%m-%d")
if df.empty:
    st.warning("노션 데이터가 없습니다. NOTION_TOKEN / DB 연결을 확인하세요.")
else:
    df["수집일"] = pd.to_datetime(df["수집일"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul")
    today_df = df[df["수집일"].dt.strftime("%Y-%m-%d") == today]
    m = st.columns(4)
    m[0].metric("총 수집 아티클", len(df))
    m[1].metric("오늘 수집", len(today_df))
    m[2].metric("오늘 발행", int((today_df["상태"] == "Published").sum()))
    m[3].metric("누적 발행", int((df["상태"] == "Published").sum()))

    st.subheader("도메인별 통계")
    st.bar_chart(df["도메인"].value_counts())

    st.subheader("최근 수집된 글")
    st.dataframe(df.head(30), use_container_width=True, hide_index=True,
                 column_config={"원문": st.column_config.LinkColumn(), "티스토리": st.column_config.LinkColumn()})

# ─────────────────────────── 광고 수익 ───────────────────────────
st.subheader("💰 광고 수익")
st.caption("애드센스 API는 OAuth 앱 승인이 필요해, 일별 수익을 직접 입력/CSV 업로드하는 방식입니다.")

rev = pd.read_csv(REVENUE_CSV, parse_dates=["date"]) if REVENUE_CSV.exists() else pd.DataFrame(
    {"date": pd.to_datetime([]), "revenue": []})

with st.expander("수익 입력"):
    a, b, c = st.columns([2, 2, 1])
    d = a.date_input("날짜")
    v = b.number_input("수익(원)", min_value=0.0, step=100.0)
    if c.button("추가"):
        rev = pd.concat([rev[rev["date"] != pd.Timestamp(d)],
                         pd.DataFrame({"date": [pd.Timestamp(d)], "revenue": [v]})]).sort_values("date")
        REVENUE_CSV.parent.mkdir(parents=True, exist_ok=True)
        rev.to_csv(REVENUE_CSV, index=False)
        st.rerun()
    up = st.file_uploader("CSV 업로드 (date,revenue)", type="csv")
    if up is not None:
        new = pd.read_csv(up, parse_dates=["date"])[["date", "revenue"]]
        rev = pd.concat([rev, new]).drop_duplicates("date", keep="last").sort_values("date")
        rev.to_csv(REVENUE_CSV, index=False)

period = st.radio("집계 단위", ["일별", "월별", "분기별", "연도별"], horizontal=True)
if rev.empty:
    st.info("입력된 수익 데이터가 없습니다.")
else:
    freq = {"일별": "D", "월별": "M", "분기별": "Q", "연도별": "Y"}[period]
    agg = rev.set_index("date")["revenue"].resample({"M": "ME", "Q": "QE", "Y": "YE"}.get(freq, freq)).sum()
    agg.index = agg.index.to_period(freq).astype(str)
    k = st.columns(3)
    k[0].metric("오늘 수익", f"{rev.loc[rev['date'] == pd.Timestamp(today), 'revenue'].sum():,.0f}원")
    k[1].metric(f"최근 {period[:-1]}", f"{agg.iloc[-1]:,.0f}원")
    k[2].metric("누적", f"{rev['revenue'].sum():,.0f}원")
    st.bar_chart(agg)
