"""3dflowhub 대시보드 — 실행: streamlit run app.py"""
from __future__ import annotations

import json
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
            st.subheader("카테고리별")
            st.bar_chart(df.assign(분류=df["도메인"] + " › " + df["카테고리"].fillna(""))["분류"].value_counts(),
                         horizontal=True)
        with b:
            st.subheader("일별 수집 추이")
            st.line_chart(df.groupby(df["수집일"].dt.date).size())
        st.subheader("최근 글")
        cols = st.columns(3)
        for i, (_, r) in enumerate(df.head(6).iterrows()):
            with cols[i % 3]:
                if isinstance(r.get("이미지"), str) and r["이미지"]:
                    st.image(r["이미지"], use_container_width=True)
                st.markdown(f"**[{r['제목']}]({r['원문']})**  \n<small>{r['도메인']} › {r['카테고리']}</small>",
                            unsafe_allow_html=True)

# ─────────────────────────── 글 목록 ───────────────────────────
with t_list:
    if df.empty:
        st.info("수집된 글이 없습니다.")
    else:
        c1, c4, c2, c3 = st.columns([2, 2, 2, 3])
        dom = c1.multiselect("도메인", sorted(df["도메인"].dropna().unique()))
        cat = c4.multiselect("카테고리", sorted(df["카테고리"].replace("", pd.NA).dropna().unique()))
        stat = c2.multiselect("상태", sorted(df["상태"].dropna().unique()))
        q = c3.text_input("검색 (제목·태그)")
        view = df
        if dom:
            view = view[view["도메인"].isin(dom)]
        if cat:
            view = view[view["카테고리"].isin(cat)]
        if stat:
            view = view[view["상태"].isin(stat)]
        if q:
            view = view[view["제목"].str.contains(q, case=False) | view["태그"].str.contains(q, case=False)]
        st.caption(f"{len(view)}건")
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"이미지": st.column_config.ImageColumn(width="small"),
                                    "원문": st.column_config.LinkColumn(),
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
        for e in [x for x in last.get("errors", []) if "news.google.com" not in x]:  # 구글 뉴스 0건은 정상
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

    st.subheader("🧬 자율 진화 현황 (strategy.json)")
    try:
        strat = requests.get(f"https://raw.githubusercontent.com/{GH_REPO}/main/memory/strategy.json", timeout=10).json()
    except Exception:
        strat = core.load_strategy()
    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**AI가 스스로 만든 편집 가이드**")
        for n in strat.get("prompt_notes", []):
            st.markdown(f"- {n}")
        st.markdown("**자동 추가된 피드**")
        for d, urls in strat.get("extra_feeds", {}).items():
            for u in urls:
                st.markdown(f"- {d}: {u}")
        if strat.get("blocked_feeds"):
            st.caption("차단된 피드: " + ", ".join(strat["blocked_feeds"]))
    with s2:
        st.markdown("**변경 이력**")
        for h in reversed(strat.get("history", [])[-8:]):
            st.markdown(f"- `{h.get('at', '')[:16]}` {h.get('lesson', '')} "
                        f"{'; '.join(h.get('changes', []) + h.get('taxonomy_merges', []))}")
    st.markdown("**현재 세부 카테고리**")
    st.json(core.load_categories(), expanded=False)

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
    n_drafts = len(list(core.DRAFT_DIR.glob("*.html"))) if core.DRAFT_DIR.exists() else 0
    if n_drafts == 0:
        st.info("발행 대기 중인 초안이 없습니다. 위의 '🚀 지금 바로 자료 수집' 을 실행하면 새 초안이 생깁니다.")
    else:
        st.success(f"발행 대기 초안 {n_drafts}개 · 하루 최대 3개까지 발행됩니다.")
    b1, b2, b3 = st.columns(3)
    pub_public = b3.toggle("공개 발행", value=False, help="끄면 비공개로 발행됩니다")

    def _publisher(*args: str) -> None:
        import subprocess, sys
        with st.spinner("티스토리 작업 중… (글 사이 60초 간격)"):
            r = subprocess.run([sys.executable, "tistory_publisher.py", *args], cwd=core.ROOT,
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        st.code(((r.stdout or "") + (r.stderr or ""))[-3000:] or "출력 없음")

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
    st.subheader("📈 성과 (수익 학습 보상 신호)")
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
    latest = perf.get("latest", {})
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("누적 조회수", latest.get("pv_total", 0))
    p2.metric("최근 30일 글 조회수", latest.get("pv_30d_posts", 0))
    p3.metric("최근 30일 수익", f"{latest.get('revenue_30d', 0):,.0f}원")
    p4.metric("RPM (1,000뷰당)", f"{latest.get('rpm_30d', 0):,.0f}원")
    if st.button("📊 티스토리 성과 수집 (조회수 → 노션 → AI 학습)"):
        import subprocess, sys
        with st.spinner("통계 수집 중…"):
            r = subprocess.run([sys.executable, "monetize.py"], cwd=core.ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        st.code(((r.stdout or "") + (r.stderr or ""))[-1500:] or "출력 없음")
    if latest.get("posts"):
        st.dataframe(pd.DataFrame([{"글": v["title"], "조회수": v["views"], "주소": k}
                                   for k, v in latest["posts"].items()]).sort_values("조회수", ascending=False),
                     use_container_width=True, hide_index=True,
                     column_config={"주소": st.column_config.LinkColumn()})
    if latest.get("inflow"):
        st.caption("유입: " + json.dumps({k: v.get("total") for k, v in latest["inflow"].items()
                                          if isinstance(v, dict)}, ensure_ascii=False))
    st.caption(f"수집 시각: {latest.get('at', '-')}  ·  AI는 노션 Views 를 보고 도메인 비중·편집 가이드를 조정합니다.")
    st.divider()
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
