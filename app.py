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

# ─────────────────────────── 데이터 ───────────────────────────
@st.cache_data(ttl=300)
def load_rows() -> pd.DataFrame:
    return pd.DataFrame(core.fetch_dashboard_rows())


@st.cache_data(ttl=120)
def load_runs() -> list[dict]:
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_REPO}/actions/runs?per_page=15", timeout=10)
        return r.json().get("workflow_runs", [])
    except Exception:
        return []


@st.cache_data(ttl=120)
def load_remote_memory() -> dict:
    """GitHub 의 최신 memory.json (클라우드 실행 결과). 실패 시 로컬 파일."""
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{GH_REPO}/main/memory/memory.json", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return core.load_memory()


if st.button("🔄 새로고침"):
    st.cache_data.clear()
    st.rerun()

df = load_rows()
today = datetime.now().strftime("%Y-%m-%d")
if not df.empty:
    df["수집일"] = pd.to_datetime(df["수집일"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul")

t_home, t_list, t_auto, t_draft, t_rev = st.tabs(["📊 현황", "📰 글 목록", "⚙️ 자동화 상태", "📝 티스토리 초안", "💰 광고 수익"])

# ─────────────────────────── 현황 ───────────────────────────
with t_home:
    if df.empty:
        st.warning("노션 데이터가 없습니다. NOTION_TOKEN / DB 연결을 확인하세요.")
    else:
        today_df = df[df["수집일"].dt.strftime("%Y-%m-%d") == today]
        m = st.columns(4)
        m[0].metric("총 수집 아티클", len(df))
        m[1].metric("오늘 수집", len(today_df))
        m[2].metric("오늘 발행", int((today_df["상태"] == "Published").sum()))
        m[3].metric("누적 발행", int((df["상태"] == "Published").sum()))
        a, b = st.columns(2)
        with a:
            st.subheader("도메인별")
            st.bar_chart(df["도메인"].value_counts(), horizontal=True)
        with b:
            st.subheader("일별 수집 추이")
            st.line_chart(df.groupby(df["수집일"].dt.date).size())
        st.subheader("최근 5건")
        for _, r in df.head(5).iterrows():
            st.markdown(f"- **[{r['도메인']}]** [{r['제목']}]({r['원문']})  \n  <small>{r['태그']}</small>",
                        unsafe_allow_html=True)

# ─────────────────────────── 글 목록 ───────────────────────────
with t_list:
    if df.empty:
        st.info("수집된 글이 없습니다.")
    else:
        c1, c2, c3 = st.columns([2, 2, 3])
        dom = c1.multiselect("도메인", sorted(df["도메인"].dropna().unique()))
        stat = c2.multiselect("상태", sorted(df["상태"].dropna().unique()))
        q = c3.text_input("검색 (제목·태그)")
        view = df
        if dom:
            view = view[view["도메인"].isin(dom)]
        if stat:
            view = view[view["상태"].isin(stat)]
        if q:
            view = view[view["제목"].str.contains(q, case=False) | view["태그"].str.contains(q, case=False)]
        st.caption(f"{len(view)}건")
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"원문": st.column_config.LinkColumn(),
                                    "티스토리": st.column_config.LinkColumn(),
                                    "수집일": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
        st.link_button("노션 DB 열기", f"https://app.notion.com/p/{core.NOTION_DATABASE_ID}")

# ─────────────────────────── 자동화 상태 ───────────────────────────
with t_auto:
    mem = load_remote_memory()
    st.subheader("마지막 수집 결과")
    if mem.get("runs"):
        last = mem["runs"][-1]
        k = st.columns(4)
        k[0].metric("수집", last.get("collected", 0))
        k[1].metric("노션 저장", last.get("saved", 0))
        k[2].metric("발행", last.get("published", 0))
        k[3].metric("초안", last.get("drafts", 0))
        st.caption(f"실행 시각(UTC): {last.get('at', '')[:19]}  ·  GitHub 최신 기록")
        for e in last.get("errors", []):
            st.error(e)
    else:
        st.info("기록이 없습니다.")

    st.subheader("GitHub Actions 실행 기록")
    runs = load_runs()
    if runs:
        icon = {"success": "✅", "failure": "❌", "cancelled": "⏹️", None: "⏳"}
        rows = [{"": icon.get(r["conclusion"], "❔"),
                 "워크플로": r["name"],
                 "방식": {"schedule": "자동", "workflow_dispatch": "수동"}.get(r["event"], r["event"]),
                 "시작(KST)": pd.Timestamp(r["created_at"]).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M"),
                 "링크": r["html_url"]} for r in runs]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     column_config={"링크": st.column_config.LinkColumn(display_text="열기")})
        if not any(r["event"] == "schedule" for r in runs):
            st.warning("아직 자동(스케줄) 실행 기록이 없습니다. 깃허브 크론이 시작되기까지 시간이 걸릴 수 있습니다.")
    else:
        st.info("실행 기록을 불러오지 못했습니다.")

    st.subheader("에이전트 교훈 (memory.json)")
    for l in reversed(mem.get("lessons", [])[-10:]):
        st.markdown(f"- {l}")
    with st.expander("TODO.md"):
        st.markdown((core.ROOT / "TODO.md").read_text(encoding="utf-8"))

# ─────────────────────────── 티스토리 초안 ───────────────────────────
with t_draft:
    st.caption("티스토리 Open API 종료로 자동 발행 대신 HTML 초안을 만듭니다. "
               "티스토리 글쓰기 → 우측 상단 '기본모드' → **HTML** 로 바꾼 뒤 붙여넣으세요.")
    drafts = sorted(core.DRAFT_DIR.glob("*.html"), reverse=True) if core.DRAFT_DIR.exists() else []
    st.link_button("GitHub Actions 초안(Artifacts) 받기", f"https://github.com/{GH_REPO}/actions")

    st.markdown("**브라우저 자동 발행** (이 PC 전용 · 최초 1회 `python tistory_publisher.py --login` 필요)")
    b1, b2, b3 = st.columns(3)
    pub_public = b3.toggle("공개 발행", value=False, help="끄면 비공개로 발행됩니다")

    def _publisher(*args: str) -> None:
        import subprocess, sys
        with st.spinner("티스토리 작업 중… (글 사이 60초 간격)"):
            r = subprocess.run([sys.executable, "tistory_publisher.py", *args], cwd=core.ROOT,
                               capture_output=True, text=True, encoding="utf-8")
        st.code((r.stdout + r.stderr)[-3000:] or "출력 없음")

    if b1.button("🧪 테스트 (발행 안 함)"):
        _publisher("--dry-run")
    if b2.button("🚀 초안 발행 (최대 5개)", type="primary"):
        _publisher("--publish", "--limit", "5", *(["--public"] if pub_public else []))
    if not drafts:
        st.info("이 PC에 저장된 초안이 없습니다. (클라우드 실행 초안은 위 버튼 → 실행 → Artifacts 에서 받기)")
    for f in drafts[:30]:
        raw = f.read_text(encoding="utf-8")
        title = raw.split("TITLE: ", 1)[-1].split(" |", 1)[0] if raw.startswith("<!-- TITLE") else f.stem
        with st.expander(title):
            body = raw.split("-->\n", 1)[-1]
            st.code(body, language="html")
            st.download_button("HTML 다운로드", body, file_name=f.name, key=f.name)

# ─────────────────────────── 광고 수익 ───────────────────────────
with t_rev:
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
