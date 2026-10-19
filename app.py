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

# 크롬 자동 번역이 화면을 바꾸면 Streamlit(React)이 'removeChild' 오류를 냄 → 한국어 페이지로 표시하고 번역 금지
st.html("""<script>
const d = document;  // st.html 은 iframe 없이 본문에 바로 삽입됨
d.documentElement.lang = "ko";
d.documentElement.setAttribute("translate", "no");
d.documentElement.classList.add("notranslate");
if (!d.querySelector('meta[name="google"]')) {
  const m = d.createElement("meta"); m.name = "google"; m.content = "notranslate"; d.head.appendChild(m);
}
</script>""", unsafe_allow_javascript=True)


def password_gate() -> None:
    """인터넷 현황판 잠금: Secrets 의 DASHBOARD_PASSWORD 와 같아야 열림 (비공개 앱 설정에 더한 2중 잠금).
    클라우드에서 비밀번호가 설정되지 않았으면 아예 열지 않음."""
    import hmac
    pw = os.getenv("DASHBOARD_PASSWORD", "")
    if not core.CLOUD and not pw:
        return  # 이 PC 에서는 잠금 없음
    if not pw:
        st.error("인터넷 현황판은 Secrets 에 DASHBOARD_PASSWORD 를 설정해야 열립니다.")
        st.stop()
    if st.session_state.get("auth_ok"):
        return
    st.markdown("### 🧊 3dflowhub 현황판")
    with st.form("login", border=True):
        typed = st.text_input("비밀번호", type="password")
        if st.form_submit_button("들어가기", type="primary"):
            if hmac.compare_digest(typed.encode(), pw.encode()):
                st.session_state.auth_ok = True
                st.rerun()
            st.error("비밀번호가 맞지 않습니다")
    st.stop()


password_gate()
REVENUE_CSV = Path(core.ROOT) / "memory" / "revenue.csv"
GH_REPO = os.getenv("GH_REPO", "HEO-J-H/3dflowhub")
GH_PAT = os.getenv("GH_PAT", "")  # workflow_dispatch 원격 트리거용 (repo: actions write)
SITE_URL = "https://heo-j-h.github.io/3dflowhub/"
INTERVAL_MIN = {"계속": 10, "10분 단위": 10, "1시간 단위": 60, "하루 단위": 1440, "1주일 단위": 10080}

# 화면 스타일: 게시판 사이트와 같은 톤 (카드·여백·위계)
st.markdown("""<style>
[data-testid="stMetric"]{background:var(--secondary-background-color);border-radius:16px;padding:14px 18px}
[data-testid="stMetricLabel"] p{font-size:13px;opacity:.75}
[data-testid="stMetricValue"]{font-size:1.75rem}
@media (max-width: 640px){
  .block-container{padding:3.4rem 0.75rem 3rem !important}  /* 위쪽 고정 막대에 가리지 않게 */
  h1{font-size:1.55rem !important;padding:0.2rem 0 0.4rem !important}
  h2,h3{font-size:1.15rem !important}
  [data-testid="stMetricValue"]{font-size:1.3rem}
  [data-testid="stMetric"]{padding:10px 12px}
  /* 지표가 한 줄에 하나씩 세로로 길게 쌓이지 않도록 2열 */
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){flex-wrap:wrap !important;gap:8px !important}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]{
    flex:1 1 calc(50% - 8px) !important;min-width:calc(50% - 8px) !important;width:auto !important}
  .stButton button,.stDownloadButton button{min-height:44px}
  [data-testid="stTabs"] button p{font-size:0.92rem}
}
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:16px}
.status-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
.hdr-links a{margin-right:14px;text-decoration:none}
section[data-testid="stSidebar"] h3{font-size:15px;margin-top:6px}
</style>""", unsafe_allow_html=True)

cfg = core.load_config()


# ─────────────────────────── 데이터 ───────────────────────────
@st.cache_data(ttl=300)
def load_rows() -> pd.DataFrame:
    return pd.DataFrame(core.fetch_dashboard_rows())


@st.cache_data(ttl=60)
def load_runs() -> list[dict]:
    """GitHub Actions 실행 기록. 로그인 없이 API 를 부르면 시간당 60회 제한에 자주 걸리므로
    GH_PAT 가 있으면 인증(시간당 5,000회), 실패하면 Actions 웹페이지의 상태 표시를 읽어 대체."""
    headers = {"Authorization": f"Bearer {GH_PAT}"} if GH_PAT else {}
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_REPO}/actions/runs?per_page=20", headers=headers, timeout=10)
        runs = r.json().get("workflow_runs", [])
        if runs:
            return runs
    except Exception:
        pass
    try:  # 대체: 웹페이지 aria-label "completed successfully: Run 384 of 3dflowhub auto curation."
        import html as _html
        import re as _re
        t = requests.get(f"https://github.com/{GH_REPO}/actions", timeout=10).text
        out = []
        for state, name in _re.findall(r'aria-label="([^":]+): Run \d+ of ([^."]+)', t):
            concl = {"completed successfully": "success", "failed": "failure", "cancelled": "cancelled"}.get(state)
            out.append({"name": _html.unescape(name).strip(), "conclusion": concl, "created_at": ""})
        return out
    except Exception:
        return []



@st.cache_data(ttl=60)
def load_remote_memory() -> dict:
    """GitHub 의 최신 memory.json (클라우드 실행 결과). 실패 시 로컬 파일."""
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{GH_REPO}/main/memory/memory.json", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return core.load_memory()


def kst(ts: str) -> str:
    """UTC ISO 시각 → 한국 시간 'YYYY-MM-DD HH:MM'."""
    try:
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        return t.tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def ago(ts: str) -> str:
    """ISO 시각 → '3분 전' 같은 사람이 읽기 쉬운 표현."""
    try:
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        mins = int((pd.Timestamp.now(tz="UTC") - t).total_seconds() // 60)
    except Exception:
        return "-"
    return "방금" if mins < 1 else f"{mins}분 전" if mins < 60 else f"{mins // 60}시간 전" if mins < 1440 else f"{mins // 1440}일 전"


# ─────────────────────────── 사이드바: 실시간 상태 + 빠른 실행 ───────────────────────────
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


@st.fragment(run_every="60s")  # 사이드바 상태만 1분마다 갱신 (전체 페이지 재실행 없음)
def status_panel() -> None:
    runs = load_runs()
    mem = load_remote_memory()
    last = (mem.get("runs") or [{}])[-1]
    cur = [r for r in runs if r["name"].startswith("3dflowhub auto")]
    ok = cur and cur[0]["conclusion"] in ("success", None)
    color = "#8e8e93" if not runs else "#30d158" if ok else "#ff453a"
    label = "상태 조회 불가 (GitHub 조회 제한·네트워크)" if not runs else "정상" if ok else "확인 필요"
    st.markdown(f'<span class="status-dot" style="background:{color}"></span>**자동 수집 {label}**',
                unsafe_allow_html=True)
    st.caption(f"주기 {cfg['interval']} · 마지막 수집 {ago(last.get('at', ''))} "
               f"(수집 {last.get('collected', 0)} → 저장 {last.get('saved', 0)})")
    used, budget = core.llm_usage_today(), int(cfg.get("llm_daily_budget", 500))
    q = core.llm_quota_status()
    fb = core.llm_fallback_usage()
    st.progress(1.0 if q["exhausted"] else min(1.0, used / budget) if budget else 1.0,
                text=f"AI 사용 {used}/{budget}회" + (" · 한도 소진(16~17시 리셋)" if q["exhausted"] else "")
                + "".join(f" · 예비 {k} {v}회" for k, v in fb.items()))
    if q["learned_limit"] and q["learned_limit"] < budget:
        st.caption(f"⚠️ 실제 Gemini 한도 약 {q['learned_limit']}회 — 설정값을 낮추세요")
    pages = [r for r in runs if r["name"].endswith("pages")]
    if pages:
        st.caption(f"사이트 배포 {ago(pages[0]['created_at']) if pages[0].get('created_at') else '최근'} · {'✅' if pages[0]['conclusion'] == 'success' else '⏳' if pages[0]['conclusion'] is None else '❌'}")


@st.fragment(run_every="3s")  # 수집 중엔 3초마다 진행 상태 자동 갱신 (새로고침 불필요)
def job_panel() -> None:
    if job["running"]:
        st.info("⏳ 수집 중… 피드 확인과 요약에 몇 분 걸립니다")
    elif job["result"]:
        r = job["result"]
        st.success(f"완료: 수집 {r.get('collected', 0)} → 저장 {r.get('saved', 0)}건")
        for e in r.get("errors", [])[:3]:
            st.caption(f"· {e[:120]}")
    elif job["error"]:
        st.error(job["error"])


# ─────────────────────────── 사이트 전환 (HQ: 여러 사이트를 한 현황판에서) ───────────────────────────
import sites as _sites  # noqa: E402

VIEW_LABELS = {"hq": "🏢 전체 요약", **{k: v["name"] for k, v in _sites.SITES.items()}}
# 휴대폰에서는 사이드바가 접혀 있으므로 본문 맨 위에 둠
SHORT = {"hq": "🏢 전체", "3dflowhub": "🧊 3dflowhub", "life-after-60": "💰 은퇴계산기"}  # 휴대폰 한 줄에 들어가게
view = st.segmented_control("사이트", list(VIEW_LABELS), default="3dflowhub",
                            format_func=lambda k: SHORT.get(k, VIEW_LABELS[k]),
                            key="site_view", label_visibility="collapsed") or "3dflowhub"
if view != "3dflowhub":
    import dash_sites
    with st.sidebar:
        st.caption("🔔 각 사이트의 결정·홍보·팀은 여기서, 수집·가이드·배포 설정은 🧊 3dflowhub 화면에서")
        if st.button("🔄 데이터 새로고침", width="stretch", key="hq_refresh"):
            st.cache_data.clear()
            core.git_sync()
            st.rerun()
    if view == "hq":
        dash_sites.render_hq()
    else:
        dash_sites.render_site(view)
    st.stop()

with st.sidebar:
    st.markdown("### 🧊 3dflowhub")
    status_panel()
    st.divider()
    left = core.llm_budget_left()
    if core.CLOUD:
        st.caption("인터넷 현황판에서는 아래 '☁️ GitHub에서 실행'으로 바로 수집합니다")
    elif st.button("🚀 지금 바로 수집", type="primary", disabled=job["running"] or left <= 0,
                 width="stretch",
                 help="이 PC에서 현재 설정으로 즉시 수집합니다 (GitHub 자동 수집과 별개)"):
        job.update(running=True, result=None, error=None)
        threading.Thread(target=_run_local, daemon=True,
                         args=(job, {"max_items": cfg["max_items"], "domains": cfg["domains"],
                                     "publish": cfg["publish"]})).start()
        st.rerun()
    if left <= 0 and not job["running"]:
        st.caption(f"⏸ AI 일일 한도 소진 — {core.llm_reset_kst()}(한국시간)에 다시 켜집니다")
    job_panel()
    if GH_PAT and st.button("☁️ GitHub에서 실행", width="stretch"):
        r = requests.post(f"https://api.github.com/repos/{GH_REPO}/actions/workflows/auto_curation.yml/dispatches",
                          headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
                          json={"ref": "main", "inputs": {}}, timeout=20)
        st.toast("GitHub 실행 요청 완료" if r.status_code == 204 else f"요청 실패 {r.status_code}")
    if st.button("🔄 데이터 새로고침", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.link_button("🌐 게시판 사이트", SITE_URL, width="stretch")
    st.link_button("📝 티스토리", "https://hjh1014.tistory.com/", width="stretch")
    st.link_button("⚙️ GitHub Actions", f"https://github.com/{GH_REPO}/actions", width="stretch")

# ─────────────────────────── 알림 ───────────────────────────
@st.cache_data(ttl=6 * 3600)
def cached_token_expiry() -> str:
    """GH_PAT 만료일 (6시간마다 확인). 클라우드에서 알아내면 config 에 기록 → 이 PC 현황판에도 보임."""
    import alerts
    exp = alerts.token_expiry()
    if exp and core.CLOUD and core.load_config().get("gh_pat_expires") != str(exp):
        core.save_config({"gh_pat_expires": str(exp)})
        core.git_sync(["config.json"], "chore(config): GitHub 토큰 만료일 기록 [skip ci]")
    return str(exp) if exp else ""


def show_alerts() -> list[dict]:
    import alerts
    from datetime import date as _date
    exp = cached_token_expiry()
    items = alerts.collect(core.load_config(), load_runs(), (load_remote_memory().get("runs") or [{}])[-1],
                           _date.fromisoformat(exp) if exp else None)
    urgent = [a for a in items if a["level"] in ("error", "warning")]
    for a in urgent[:4]:
        (st.error if a["level"] == "error" else st.warning)(f"**{a['title']}** — {a['detail']}", icon=alerts.ICON[a["level"]])
    rest = [a for a in items if a not in urgent[:4]]
    if rest:
        with st.expander((f"🔔 그 밖의 알림 {len(rest)}개" if urgent[:4] else f"🔔 알림 {len(rest)}개 · 급한 일 없음")):
            for a in rest:
                st.markdown(f"{alerts.ICON[a['level']]} **{a['title']}**  \n<span style='opacity:.7'>{a['detail']}</span>",
                            unsafe_allow_html=True)
    return items


# ─────────────────────────── 본문 ───────────────────────────
st.title("큐레이션 현황판")
alert_items = show_alerts()
with st.sidebar:
    n_urgent = sum(a["level"] != "info" for a in alert_items)
    st.caption(f"🔔 알림 {len(alert_items)}개" + (f" · 확인 필요 {n_urgent}개" if n_urgent else ""))
df = load_rows()
today = datetime.now().strftime("%Y-%m-%d")
if not df.empty:
    df["수집일"] = pd.to_datetime(df["수집일"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul")

t_today, t_home, t_list, t_auto, t_draft, t_rev, t_set = st.tabs(
    ["🏠 오늘", "📊 개요", "📰 글 목록", "🧬 자동화·진화", "📝 티스토리", "💰 수익·방문", "🛠 설정"])

# ─────────────────────────── 개요 ───────────────────────────
with t_home:
    if df.empty:
        st.warning("아직 수집된 글이 없습니다.")
    else:
        day = df["수집일"].dt.strftime("%Y-%m-%d")
        yday = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        n_today, n_yday = int((day == today).sum()), int((day == yday).sum())
        perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
        m = st.columns(5)
        m[0].metric("전체 글", f"{len(df):,}", f"+{n_today} 오늘")
        m[1].metric("오늘 수집", n_today, n_today - n_yday, help="어제 대비")
        m[2].metric("도구·주제 게시판", df[["도메인", "카테고리"]].drop_duplicates().shape[0])
        m[3].metric("사이트 방문 (30일)", (perf.get("pages") or {}).get("pv_30d", "미연결"))
        m[4].metric("AI 사용 (오늘)", f"{core.llm_usage_today()}/{cfg.get('llm_daily_budget', 500)}")

        with st.container(border=True):
            st.markdown("**최근 14일 수집 추이**")
            daily = df.assign(날짜=df["수집일"].dt.date).groupby(["날짜", "도메인"]).size().unstack(fill_value=0)
            daily = daily[daily.index >= (datetime.now() - pd.Timedelta(days=14)).date()]
            st.bar_chart(daily, height=220)
        a, b = st.columns(2)
        with a, st.container(border=True):
            st.markdown("**많이 다룬 도구 Top 10**")
            top = (df["도메인"] + " › " + df["카테고리"].fillna("기타")).value_counts().head(10).sort_values()
            st.bar_chart(top, horizontal=True, height=300)
        with b, st.container(border=True):
            st.markdown("**콘텐츠 유형 분포**")
            if "유형" in df.columns:
                st.bar_chart(df["유형"].replace("", "미분류").value_counts().sort_values(), horizontal=True, height=300)
        st.markdown("**최근 글**")
        cols = st.columns(3)
        for i, (_, r) in enumerate(df.head(6).iterrows()):
            with cols[i % 3], st.container(border=True):
                if isinstance(r.get("이미지"), str) and r["이미지"]:
                    st.image(r["이미지"], width="stretch")
                link = r.get("사이트") if isinstance(r.get("사이트"), str) else r["원문"]
                st.markdown(f"**[{r['제목']}]({link})**")
                st.caption(f"{r['도메인']} › {r['카테고리']}" + (f" · {r['유형']}" if r.get("유형") else ""))

# ─────────────────────────── 글 목록 ───────────────────────────
with t_list:
    if df.empty:
        st.info("수집된 글이 없습니다.")
    else:
        c1, c4, c5, c2, c3 = st.columns([2, 2, 2, 2, 3])
        dom = c1.multiselect("도메인", sorted(df["도메인"].dropna().unique()))
        cat = c4.multiselect("도구·제품", sorted(df["카테고리"].replace("", pd.NA).dropna().unique()))
        topic = c5.multiselect("유형", core.TOPICS) if "유형" in df.columns else []
        stat = c2.multiselect("상태", sorted(df["상태"].dropna().unique()))
        q = c3.text_input("검색 (제목·태그)")
        view = df
        if dom:
            view = view[view["도메인"].isin(dom)]
        if cat:
            view = view[view["카테고리"].isin(cat)]
        if topic:
            view = view[view["유형"].isin(topic)]
        if stat:
            view = view[view["상태"].isin(stat)]
        if q:
            view = view[view["제목"].str.contains(q, case=False) | view["태그"].str.contains(q, case=False)]
        st.caption(f"{len(view)}건")
        st.caption("✅ **추천**한 글은 사이트 홈 '에디터 추천'에 올라가고, 🚫 **숨김**한 글은 사이트에서 빠집니다. "
                   "숨길 때 **숨김 사유**(예: 주제와 무관, 번역 이상, 광고성)를 적으면 AI 관리자가 같은 유형을 덜 모으도록 학습합니다.")
        edited = st.data_editor(
            view, width="stretch", hide_index=True, key="curate",
            disabled=[c for c in view.columns if c not in ("추천", "숨김", "숨김 사유")],
            column_order=["추천", "숨김", "숨김 사유"] + [c for c in view.columns
                                                     if c not in ("추천", "숨김", "숨김 사유", "ID")],
            column_config={"추천": st.column_config.CheckboxColumn("✅ 추천", width="small"),
                           "숨김": st.column_config.CheckboxColumn("🚫 숨김", width="small"),
                           "숨김 사유": st.column_config.SelectboxColumn(
                               "숨김 사유", width="medium",
                               options=["", "주제와 무관", "번역·용어 이상", "광고·홍보성", "중복 기사", "내용 부실", "기타"]),
                           "이미지": st.column_config.ImageColumn(width="small"),
                           "원문": st.column_config.LinkColumn(),
                           "사이트": st.column_config.LinkColumn(display_text="게시판 보기"),
                           "티스토리": st.column_config.LinkColumn(),
                           "수집일": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
        if "ID" in view.columns:
            changes, reasons = {}, {}
            for (_, a), (_, b) in zip(view.iterrows(), edited.iterrows()):
                if (a["추천"], a["숨김"], a.get("숨김 사유", "")) != (b["추천"], b["숨김"], b.get("숨김 사유", "")):
                    changes[b["ID"]] = "hide" if b["숨김"] or b.get("숨김 사유") else "pick" if b["추천"] else ""
                    if b.get("숨김 사유"):
                        reasons[b["ID"]] = b["숨김 사유"]
            if changes and st.button(f"💾 선택 {len(changes)}건 저장 · 사이트에 반영", type="primary"):
                core.set_curation(changes, reasons)
                err = core.git_sync(["memory/curation.json"], "chore(curation): 에디터 추천/숨김")
                if err:
                    st.error(f"로컬 저장됨, GitHub 반영 실패: {err}")
                else:
                    st.toast("✅ 저장됨 — 다음 사이트 배포부터 반영됩니다")
                st.cache_data.clear()

    # 기초 가이드 검토: AI 가 만든 가이드를 사람이 확인 → '검토 완료' 표시 또는 사이트에서 숨김
    import guides as _guides
    all_g = _guides.load_all()
    gstate = core.curation_state()
    unreviewed = [g for g in all_g if not gstate.get("learn:" + g["id"])]
    with st.expander(f"📚 기초 가이드 검토 — 검토 대기 {len(unreviewed)}개 / 전체 {len(all_g)}개"):
        st.caption("사이트에서 내용을 확인한 뒤 '검토 완료'를 누르면 가이드에 ✔ 검토됨 표시가 붙고, "
                   "틀린 내용이 있으면 '숨김'으로 사이트에서 뺍니다.")
        for g in unreviewed[:15]:
            c1, c2, c3 = st.columns([5, 1, 1])
            c1.markdown(f"[{g['tool']} · {g['title']}]({SITE_URL}learn/{g['id']}/)")
            if c2.button("✔ 검토 완료", key=f"rev_{g['id']}"):
                core.set_curation({"learn:" + g["id"]: "ok"})
                core.git_sync(["memory/curation.json"], "chore(curation): 기초 가이드 검토")
                st.rerun()
            if c3.button("숨김", key=f"ghide_{g['id']}"):
                core.set_curation({"learn:" + g["id"]: "hide"}, {"learn:" + g["id"]: "가이드 내용 오류"})
                core.git_sync(["memory/curation.json"], "chore(curation): 기초 가이드 숨김")
                st.rerun()
        if not unreviewed:
            st.success("모든 가이드를 검토했습니다")

    # 운영자 실무 팁: AI 가 흉내 낼 수 없는 '직접 해 본 경험' — 사이트 차별성·신뢰의 핵심
    with st.expander("✍️ 운영자 실무 팁 쓰기 — 사이트에 '운영자 실무 팁'으로 표시됩니다"):
        st.caption("직접 써 보며 얻은 요령, 자주 막히는 지점, 회사에서 쓰는 방법 등 한두 줄이면 충분합니다. "
                   "비우고 저장하면 삭제됩니다. 팁을 단 가이드는 검토 완료로도 표시돼요.")
        tip_map = core.tips()
        kind = st.radio("대상", ["📚 기초 가이드", "📰 소식 글"], horizontal=True, key="tip_kind")
        if kind == "📚 기초 가이드":
            opts = {f"learn:{g['id']}": f"{g['tool']} · {g['title']}" + (" ✍️" if tip_map.get(f"learn:{g['id']}") else "")
                    for g in all_g}
        else:
            recent = df.head(60) if not df.empty and "ID" in df.columns else df
            opts = {f"p:{r['ID']}": f"{r['카테고리']} · {r['제목']}" + (" ✍️" if tip_map.get(f"p:{r['ID']}") else "")
                    for _, r in recent.iterrows()} if "ID" in recent.columns else {}
        if opts:
            target = st.selectbox("어느 글에", list(opts), format_func=lambda k: opts[k], key="tip_target")
            text = st.text_area("실무 팁", tip_map.get(target, ""), height=120, key=f"tip_text_{target}",
                                placeholder="예: Bend 는 Segments 를 축 방향으로 최소 20 이상 주고, Limits 로 끝만 휘게 하면 파이프 이음새가 깔끔해요.")
            if st.button("💾 팁 저장 · 사이트 반영", type="primary", key="tip_save"):
                core.set_tip(target, text)
                paths = ["memory/tips.json"]
                if target.startswith("learn:") and text.strip():
                    core.set_curation({target: "ok"})
                    paths.append("memory/curation.json")
                err = core.git_sync(paths, "content(tips): 운영자 실무 팁")
                if err:
                    st.error(f"이 PC에는 저장됐지만 GitHub 반영 실패: {err}")
                else:
                    st.toast("✅ 저장 — 몇 분 뒤 사이트에 표시됩니다")
                st.rerun()

# ─────────────────────────── 자동화 상태 ───────────────────────────
@st.cache_data(ttl=300)
def pull_latest() -> str:
    """GitHub 에서 AI 관리자 제안 등 최신 memory 를 내려받음 (5분에 한 번)."""
    return core.git_sync() or ""


def save_manager(msg: str) -> None:
    err = core.git_sync(["memory/proposals.json"], f"chore(manager): {msg} [skip ci]")
    if err:
        st.error(f"이 PC에는 저장됐지만 GitHub 반영 실패: {err}")


CAT_ICON = {"콘텐츠": "📝", "수집": "📥", "사이트·UX": "🎨", "검색(SEO)": "🔎", "운영·비용": "⚙️", "수익": "💰", "현황판": "🧭"}

with t_auto:
    import manager
    pull_latest()
    mb = manager.board()
    rep = mb["report"]
    st.subheader("🧭 AI 관리자")
    st.caption("AI가 하루 한 번 사이트·수집·검색·독자 지표를 분석해 개선안을 올립니다. "
               "수락·보류·거절과 그 이유를 남기면 다음 분석에서 취향을 배웁니다.")
    opened = [x for x in mb["proposals"] if x["status"] == "new" and (x.get("site") or "3dflowhub") == "3dflowhub"]
    rate = manager.acceptance_rate()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("검토 대기", len(opened))
    k2.metric("수락률", f"{int(rate * 100)}%" if rate is not None else "-")
    k3.metric("직접 작업 필요", len(manager.manual_todo("3dflowhub")),
              help="수락했지만 자동으로 처리할 수 없어 직접(또는 Claude 에게 맡겨) 해야 하는 일 — 아래 '🛠 직접 작업' 보기")
    k4.metric("마지막 분석", ago(rep.get("at", "")) if rep else "없음", help="AI 관리자가 마지막으로 사이트를 분석한 시각")
    if rep:
        with st.container(border=True):
            st.markdown(f"**오늘의 진단** · {kst(rep.get('at', ''))}")
            st.write(rep.get("text", ""))
    with st.container(border=True):
        t1, t2 = st.columns([3, 1.2])
        t1.markdown("**🤖 자동 모드**  \n켜면 AI 관리자가 오늘 남은 AI 사용량을 뉴스 요약·기초 가이드·도구별 정리에 "
                    "알아서 나눠 올리고, 위험이 낮은 제안(키워드·편집 지침·가이드 주제·피드)은 스스로 수락합니다. "
                    "설정 변경 제안은 계속 여기서 결정합니다.")
        on = t2.toggle("자동 모드", value=bool(cfg.get("auto_mode")), key="auto_mode_toggle")
        if on != bool(cfg.get("auto_mode")):
            core.save_config({"auto_mode": on})
            err = core.git_sync(["config.json"], f"chore(config): 자동 모드 {'켜기' if on else '끄기'}")
            if err:
                st.error(f"이 PC에는 저장됐지만 GitHub 반영 실패: {err}")
            else:
                st.toast("🤖 자동 모드를 켰습니다 — 다음 수집부터 적용" if on else "자동 모드를 껐습니다")
            st.rerun()
        plan = core._load_json(manager.PLAN_PATH, {})
        if plan.get("day") != core.llm_day():
            plan = manager.plan_today()
        if on or plan:
            tg, dn = plan.get("today_target", {}), plan.get("done", {})
            st.caption(f"오늘 남은 AI 여력 **{plan.get('capacity_left', 0)}회** · 리셋(한국 {core.llm_reset_kst()})까지 "
                       f"수집 약 {plan.get('runs_left', 0)}회 · 배분 근거: {plan.get('reason', '')}")
            c1, c2, c3 = st.columns(3)
            for col, key, label, now_key in ((c1, "news", "📰 뉴스 요약", "news_per_run"),
                                             (c2, "guides", "📚 기초 가이드", "guides_now"),
                                             (c3, "roundups", "🧭 도구별 정리", "roundups_now")):
                share = int((plan.get("alloc") or {}).get(key, 0) * 100)
                done, target = dn.get(key, 0), tg.get(key, 0)
                col.metric(f"{label} · 배분 {share}%", f"{done}건", help="오늘(태평양 자정 기준) 올린 수")
                col.caption((f"남은 목표 약 {target}건" if target else "지금은 만들 거리 없음")
                            + f" · 이번 실행 {plan.get(now_key, 0)}건" + ("" if on else " (자동 모드에서)"))
    a1, a2 = st.columns([1.4, 3])
    if a1.button("🔍 지금 분석 요청", help="AI 1회 사용 — 지금 지표로 바로 분석합니다", width="stretch"):
        with st.spinner("AI 관리자가 지표를 분석하는 중…"):
            try:
                if manager.review(force=True):
                    save_manager("AI 관리자 분석")
                    st.toast("✅ 새 분석이 올라왔습니다")
                else:
                    st.warning("AI 한도가 부족해 분석하지 못했습니다")
            except Exception as e:
                st.error(f"분석 실패: {e}")
        st.rerun()
    a2.caption("자동 분석: GitHub 수집 실행 때 하루 1회 · 의견을 보내면 다음 실행 때 답변")

    view = st.segmented_control(
        "보기", ["새 제안", "🛠 직접 작업", "수락", "보류", "거절", "완료"], default="새 제안",
        label_visibility="collapsed", key="mgr_view")
    if view == "🛠 직접 작업":
        todo = manager.manual_todo("3dflowhub")
        st.caption("수락했지만 자동 반영이 안 되는 일입니다. 직접 하시거나, '요청문'을 복사해 Claude 에게 맡긴 뒤 ✔ 완료를 눌러 주세요.")
        if not todo:
            st.success("남은 직접 작업이 없습니다")
        for x in todo:
            with st.container(border=True):
                st.markdown(f"**{x['title']}** · 제안: {x.get('by') or '🧭 AI 관리자'} · 수락 {kst(x.get('decided_at', x['at']))}")
                st.code(manager.claude_request(x), language=None, wrap_lines=True)
                if st.button("✔ 완료", key=f"done_{x['id']}", type="primary"):
                    manager.decide(x["id"], "done")
                    save_manager("직접 작업 완료")
                    st.rerun()
    want = {"새 제안": "new", "수락": "accepted", "보류": "held", "거절": "rejected", "완료": "done",
            "🛠 직접 작업": "_none"}.get(view or "새 제안", "new")
    items = [x for x in mb["proposals"] if x["status"] == want and (x.get("site") or "3dflowhub") == "3dflowhub"]
    if not items and want != "_none":  # '🛠 직접 작업' 보기는 위에서 따로 그림
        st.info({"new": "검토할 새 제안이 없습니다. '지금 분석 요청'을 누르거나 다음 자동 분석을 기다려 주세요.",
                 "accepted": "수락한 제안이 없습니다.", "held": "보류한 제안이 없습니다.",
                 "rejected": "거절한 제안이 없습니다.", "done": "완료한 제안이 없습니다."}.get(want, "제안이 없습니다."))
    for x in items[:10]:
        with st.container(border=True):
            act = x.get("action") or {}
            st.caption(f"{CAT_ICON.get(x.get('category'), '•')} {x.get('category')} · 제안: {x.get('by') or '🧭 AI 관리자'} · "
                       f"노력 {x.get('effort')} · "
                       f"{kst(x['at'])[:10]}" + (f" · 기대 효과: {x['expected']}" if x.get("expected") else ""))
            st.markdown(f"#### {x['title']}")
            st.markdown(f"**근거** — {x.get('evidence', '')}")
            st.markdown(f"**제안** — {x.get('proposal', '')}")
            st.caption(("⚡ " if act.get("type") else "🛠 ") + "수락하면: " + manager.describe(act))
            if x["status"] != "new":
                st.caption(f"결정: {manager.STATUS_KO[x['status']]}"
                           + (f" · 사유: {x['note']}" if x.get("note") else "")
                           + (f" · 반영 결과: {x['applied']}" if x.get("applied") else ""))
            if x["status"] in ("new", "held"):
                note = st.text_input("사유·메모 (선택)", key=f"note_{x['id']}", placeholder="예: 좋아요 / 비용이 커서 보류 / 방향이 달라요",
                                     label_visibility="collapsed")
                b1, b2, b3, _ = st.columns([1, 1, 1, 3])
                if b1.button("✅ 수락", key=f"acc_{x['id']}", type="primary", width="stretch"):
                    res = manager.decide(x["id"], "accepted", note)
                    save_manager("제안 수락")
                    st.toast("수락했습니다" + (f" — {res}" if res else ""))
                    st.rerun()
                if x["status"] == "new" and b2.button("⏸ 보류", key=f"hold_{x['id']}", width="stretch"):
                    manager.decide(x["id"], "held", note)
                    save_manager("제안 보류")
                    st.rerun()
                if b3.button("✕ 거절", key=f"rej_{x['id']}", width="stretch"):
                    manager.decide(x["id"], "rejected", note)
                    save_manager("제안 거절")
                    st.rerun()

    with st.expander(f"💬 관리자에게 의견·질문 보내기 ({len(mb['messages'])})"):
        with st.form("mgr_msg", clear_on_submit=True, border=False):
            txt = st.text_area("의견", placeholder="예: 3ds Max 플러그인 글을 더 모아줘 / 사이트 첫 화면이 복잡한 것 같아",
                               label_visibility="collapsed")
            if st.form_submit_button("보내기", type="primary") and txt.strip():
                manager.send_message(txt)
                save_manager("관리자에게 의견")
                st.toast("보냈습니다 — 다음 분석 때 답변합니다")
        for m in mb["messages"][:10]:
            st.markdown(f"**나** · {kst(m['at'])}  \n{m['text']}")
            st.markdown(f"> 🧭 {m['reply']}" if m["reply"] else "> ⏳ 다음 분석 때 답변 예정")

    # ── 👥 AI 팀: AI 관리자가 업무에 따라 '채용'한 직원들 ──
    import staff
    st.subheader("👥 AI 팀")
    st.caption("업무가 생기면 AI 관리자가 '채용'을 제안하고, 수락하면 새 직원이 정해진 주기마다 일합니다. "
               "직원의 결과물(홍보 글·제안)에 대한 반응을 보고 스스로 배웁니다.")
    team = staff.roles()
    box_all = staff.outbox()
    for r in [r for r in team.values() if r.get("site", "3dflowhub") == "3dflowhub"]:
        with st.container(border=True):
            mine = [x for x in box_all if x.get("role") == r["id"]]
            h1, h2 = st.columns([4, 1.4])
            h1.markdown(f"**{r['name']}** · {'🟢 근무 중' if r['status'] == 'active' else '⏸ 휴식'} · "
                        f"{r.get('every_hours')}시간마다 · 하루 AI 최대 {r.get('daily_calls')}회")
            h1.caption(r.get("mission", "")[:220])
            h1.caption(f"채용: {r.get('hired_by')}{' · ' + kst(r['hired_at']) if r.get('hired_at') else ''} · "
                       f"마지막 업무: {ago(r['last_run']) if r.get('last_run') else '아직 없음'}"
                       + (f" — {r['last_summary']}" if r.get("last_summary") else "")
                       + (f" · 홍보 글 {len(mine)}개 (게시 {sum(x['status'] == 'posted' for x in mine)}, "
                          f"건너뜀 {sum(x['status'] == 'skipped' for x in mine)})" if mine else ""))
            if h2.button("▶ 지금 일 시키기", key=f"run_{r['id']}", width="stretch", help="AI 1~2회 사용",
                         disabled=r["status"] != "active"):
                with st.spinner(f"{r['name']} 업무 중…"):
                    try:
                        res = staff.run_role(r)
                        core.git_sync(["memory/outbox.json", "memory/roles.json", "memory/proposals.json", "drafts/promo"],
                                      f"chore(staff): {r['name']} 업무 [skip ci]")
                        st.toast(f"완료 — 홍보 글 {res.get('promo', 0)}개, 제안 {res.get('proposal', 0)}개")
                    except Exception as e:
                        st.error(f"업무 실패: {e}")
                st.rerun()
            if h2.button("⏸ 쉬게 하기" if r["status"] == "active" else "▶ 다시 일하게", key=f"pause_{r['id']}",
                         width="stretch"):
                staff.set_status(r["id"], r["status"] != "active")
                core.git_sync(["memory/roles.json"], "chore(staff): 직원 상태 변경 [skip ci]")
                st.rerun()
    with st.expander("📖 업무 교본 — 에이전트들이 일하기 전에 읽는 매뉴얼 (직접 고칠 수 있음)"):
        names = {"common": "공통 (모두)", "manager": "🧭 AI 관리자", "marketer": "📣 마케터", "editor": "✍️ 에디터(요약·정리)",
                 "guide_writer": "📚 기초 가이드 작가", "dev_team": "🛠 개발팀 4대 에이전트", "new_staff": "👋 새 직원 온보딩"}
        pick = st.selectbox("교본", list(names), format_func=lambda k: names[k], key="pb_pick")
        pb_file = core.KNOWLEDGE_DIR / f"{pick}.md"
        pb_text = pb_file.read_text(encoding="utf-8") if pb_file.exists() else ""
        new_text = st.text_area("내용 (마크다운)", pb_text, height=360, key=f"pb_{pick}")
        if new_text != pb_text and st.button("💾 교본 저장", type="primary"):
            pb_file.write_text(new_text, encoding="utf-8")
            err = core.git_sync([f"knowledge/{pick}.md"], f"docs(knowledge): {names[pick]} 교본 수정 [skip ci]")
            if err:
                st.error(err)
            else:
                st.toast("저장했습니다 — 다음 업무부터 이 교본대로 일합니다")
        for r in team.values():
            if r.get("playbook"):
                st.markdown(f"**{r['name']} 직무 교본** (채용 때 AI 관리자가 작성)")
                st.markdown(r["playbook"])
    with st.expander("📣 홍보 채널 설정"):
        chans = st.text_area("마케터가 글을 써 줄 채널 (한 줄에 하나)",
                             "\n".join(cfg.get("promo_channels") or staff.DEFAULT_CHANNELS), height=120,
                             help="예: 네이버 카페 '3D 그래픽 모임', 디스코드 '블렌더 코리아', 인스타그램")
        if st.button("채널 저장"):
            core.save_config({"promo_channels": [c.strip() for c in chans.splitlines() if c.strip()][:10]})
            core.git_sync(["config.json"], "chore(config): 홍보 채널 [skip ci]")
            st.toast("저장했습니다 — 다음 업무부터 적용")

    st.divider()
    mem = load_remote_memory()
    st.subheader("마지막 수집 결과")
    if mem.get("runs"):
        last = mem["runs"][-1]
        k = st.columns(4)
        k[0].metric("수집", last.get("collected", 0))
        k[1].metric("저장", last.get("saved", 0))
        k[2].metric("발행", last.get("published", 0))
        k[3].metric("초안", last.get("drafts", 0))
        st.caption(f"실행 시각(UTC): {last.get('at', '')[:19]}  ·  GitHub 최신 기록")
        errs = [x for x in last.get("errors", []) if "news.google.com" not in x]  # 구글 뉴스 0건은 정상
        skips = {"short body": "본문이 너무 짧아 건너뜀", "off-topic": "주제와 무관해 건너뜀",
                 "prefiltered": "3D 관련 어휘가 없어 AI 요약 전에 제외"}
        counts = {"short body": last.get("short"), "off-topic": last.get("offtopic"), "prefiltered": last.get("prefiltered")}
        info = {k: counts[k] or errs.count(k) for k in skips if counts[k] or k in errs}  # 실제 건수(실행 통계) 우선
        if info:
            st.info("정상 필터링 · " + " · ".join(f"{skips[k]} {n}건" for k, n in info.items()))
        for e in dict.fromkeys(x for x in errs if x not in skips):
            if "429" in e or "한도" in e:
                st.warning(f"⏸ AI 일일 한도 소진 — 태평양 자정(한국 오후 4~5시)에 리셋되면 자동 재개됩니다.\n\n`{e[:160]}`")
            elif "delimiter" in e or "Expecting" in e:
                st.warning(f"AI 응답 JSON 형식 오류 (해당 1건만 건너뜀, 이제 자동 복구 시도) · `{e[:120]}`")
            else:
                st.error(e)
    else:
        st.info("기록이 없습니다.")

    st.subheader("GitHub Actions 실행 기록")
    runs = load_runs()
    if runs:
        icon = {"success": "✅", "failure": "❌", "cancelled": "⏹️", None: "⏳"}
        rows = [{"": icon.get(r["conclusion"], "❔"),
                 "워크플로": r["name"],
                 "방식": {"schedule": "자동", "workflow_dispatch": "수동", "push": "푸시"}.get(r.get("event"), r.get("event") or "-"),
                 "시작(KST)": pd.Timestamp(r["created_at"]).tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")
                 if r.get("created_at") else "-",
                 "링크": r.get("html_url") or f"https://github.com/{GH_REPO}/actions"} for r in runs]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                     column_config={"링크": st.column_config.LinkColumn(display_text="열기")})
        # 자동 실행은 크론(schedule) 또는 heartbeat 가 부르는 수동 실행(workflow_dispatch) 둘 다 정상
        if not any(str(r.get("name", "")).startswith("3dflowhub auto") for r in runs):
            st.warning("최근 자동 수집 실행 기록이 없습니다 — heartbeat 워크플로가 멈췄는지 확인해 주세요.")
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
        st.markdown("**독자 관심 도구 (조회수·추천 학습)**")
        ti = strat.get("tool_interest") or {}
        if ti:
            for d, tools in ti.items():
                st.markdown(f"- {d}: {', '.join(tools)}")
        else:
            st.caption("조회수가 더 쌓이면 자동으로 학습됩니다 (사이트 전체 20회 이상)")
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

    if core.CLOUD:
        st.info("브라우저 자동 발행은 로그인된 크롬이 있는 PC 에서만 됩니다. 아래 초안은 복사해서 직접 붙여넣을 수 있어요.")
    if b1.button("🧪 테스트 (발행 안 함)", disabled=core.CLOUD):
        _publisher("--dry-run")
    if b2.button("🚀 초안 발행 (최대 5개)", type="primary", disabled=core.CLOUD):
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
    perf = core._load_json(core.ROOT / "memory" / "performance.json", {})
    pages_perf = perf.get("pages") or {}
    latest = perf.get("latest", {})
    site_url = "https://heo-j-h.github.io/3dflowhub/"

    # ── 1) 메인 채널: GitHub Pages ─────────────────────────────
    st.subheader("🌐 GitHub Pages (메인 채널)")
    n_posts = len(list(core.POSTS_DIR.glob("*.json")))
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("게시 글", f"{n_posts}개")
    g2.metric("최근 30일 방문(조회)", pages_perf.get("pv_30d", "미연결") if pages_perf else "미연결")
    g3.metric("발행 제한", "없음")
    g4.metric("광고", "적용됨" if cfg.get("adsense_client") else "미적용")
    st.link_button("사이트 열기", site_url)
    if pages_perf.get("posts"):
        top = sorted(pages_perf["posts"].items(), key=lambda kv: -kv[1]["views"])[:15]
        st.dataframe(pd.DataFrame([{"글": v["title"] or k, "조회수": v["views"], "주소": f"{site_url}p/{k}.html"}
                                   for k, v in top]), width="stretch", hide_index=True,
                     column_config={"주소": st.column_config.LinkColumn()})
        if pages_perf.get("refs"):
            st.caption("유입 경로: " + " · ".join(f"{n} {c}" for n, c in pages_perf["refs"]))
        st.caption(f"수집: {pages_perf.get('at', '-')} (GitHub 자동 수집, 6시간마다) · 조회수는 노션 Views 에 합산되어 AI 학습에 쓰입니다.")

    with st.expander("⚙️ 사이트 방문 통계·광고 연결 설정", expanded=not pages_perf):
        st.markdown(
            "**① 방문 통계 (무료, GoatCounter)**\n"
            "1. [goatcounter.com](https://www.goatcounter.com/signup) 가입 → 사이트 코드 입력 (예: `3dflowhub`)\n"
            "2. 아래 칸에 코드를 넣고 저장 → 사이트에 통계 스크립트가 자동 삽입됩니다\n"
            "3. GoatCounter → Settings → **API** 에서 토큰 발급(권한: *Read statistics*) → "
            "GitHub Secrets 에 `GOATCOUNTER_TOKEN` 으로 등록하면 대시보드·AI 학습에 조회수가 들어옵니다\n\n"
            "**② 애드센스 (승인 후)** — `github.io` 주소는 승인이 어려워 **본인 도메인 연결**이 필요합니다. "
            "승인되면 `ca-pub-...` 를 넣고 저장 → 자동 광고 스크립트와 `ads.txt` 가 생성됩니다.")
        sc1, sc2 = st.columns(2)
        gc_code = sc1.text_input("GoatCounter 사이트 코드", cfg.get("goatcounter_code", ""), placeholder="3dflowhub")
        ad_client = sc2.text_input("AdSense 게시자 ID", cfg.get("adsense_client", ""), placeholder="ca-pub-0000000000000000")
        if st.button("💾 사이트 설정 저장 (GitHub 반영 → 사이트 재배포)"):
            core.save_config({**core.load_config(), "goatcounter_code": gc_code.strip(), "adsense_client": ad_client.strip()})
            err = core.git_sync(["config.json"], "chore(config): 사이트 통계·광고 설정")
            if err:
                st.error(err)
            else:
                st.success("저장됨 — 다음 사이트 배포부터 적용됩니다.")

    st.markdown("**✅ GitHub Pages 수익화 체크리스트**")
    checks = [
        ("Google Search Console 등록·사이트맵 제출", True),
        ("광고·제휴 문의 페이지 (/contact/)", True),
        ("개인정보처리방침 페이지 (/privacy/) — 애드센스 필수", True),
        ("방문 통계 연결 (GoatCounter)", bool(cfg.get("goatcounter_code"))),
        ("본인 도메인 연결 (애드센스 승인 조건)", "github.io" not in core._load_json(core.CONFIG_PATH, {}).get("site_base_url", "github.io")),
        ("애드센스 게시자 ID 등록", bool(cfg.get("adsense_client"))),
        ("네이버 서치어드바이저 등록", False),
    ]
    for label, ok in checks:
        st.markdown(f"{'✅' if ok else '⬜'} {label}")

    st.divider()
    # ── 2) 보조 채널: 티스토리 ─────────────────────────────────
    with st.expander("📝 티스토리 (보조 채널 · 하루 3개 발행)"):
        t1, t2, t3 = st.columns(3)
        t1.metric("누적 조회수", latest.get("pv_total", 0))
        t2.metric("최근 30일 글 조회수", latest.get("pv_30d_posts", 0))
        t3.metric("유입(검색)", (latest.get("inflow") or {}).get("searchEngine", {}).get("total", 0)
                  if isinstance(latest.get("inflow"), dict) else 0)
        if st.button("📊 티스토리 + Pages 성과 수집 (이 PC · 티스토리 로그인 필요)"):
            import subprocess, sys
            with st.spinner("통계 수집 중…"):
                r = subprocess.run([sys.executable, "monetize.py"], cwd=core.ROOT, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            st.code(((r.stdout or "") + (r.stderr or ""))[-1500:] or "출력 없음")
        if latest.get("posts"):
            st.dataframe(pd.DataFrame([{"글": v["title"], "조회수": v["views"], "주소": k}
                                       for k, v in latest["posts"].items()]).sort_values("조회수", ascending=False),
                         width="stretch", hide_index=True,
                         column_config={"주소": st.column_config.LinkColumn()})
        st.caption(f"수집: {latest.get('at', '-')}")

    st.divider()
    # ── 3) 광고 수익 (채널별) ──────────────────────────────────
    st.subheader("🔎 구글 검색 유입 (Search Console)")
    import gsc
    sc = core._load_json(gsc.GSC_PATH, {})
    if sc.get("queries"):
        st.caption(f"최근 {sc.get('days', 28)}일 · 갱신 {ago(sc.get('at', ''))} — AI가 이 검색어를 키워드·전략에 반영합니다")
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**노출 많은 검색어**")
            st.dataframe(pd.DataFrame(sc["queries"]).rename(columns={
                "key": "검색어", "clicks": "클릭", "impressions": "노출", "ctr": "클릭률", "position": "평균 순위"}).head(20),
                hide_index=True, width="stretch")
        with g2:
            st.markdown("**기회 검색어** (노출 많고 8~20위 — 더 좋은 글로 순위 상승 여지)")
            opp = gsc.opportunities()
            if opp:
                st.dataframe(pd.DataFrame(opp).rename(columns={"key": "검색어", "impressions": "노출",
                                                               "position": "평균 순위"})[["검색어", "노출", "평균 순위"]],
                             hide_index=True, width="stretch")
            else:
                st.caption("아직 없음")
    else:
        st.info("아직 연결되지 않았습니다. GitHub Secret `GSC_SERVICE_ACCOUNT` 를 등록하면 하루 한 번 자동 수집됩니다 "
                "(설정 방법은 gsc.py 맨 위 안내).")

    st.subheader("💰 광고 수익")
    st.caption("애드센스 API 는 OAuth 앱 승인이 필요해 일별 수익을 직접 입력/CSV 업로드합니다. 채널별로 기록하면 RPM 을 따로 계산합니다.")
    rev = pd.read_csv(REVENUE_CSV, parse_dates=["date"]) if REVENUE_CSV.exists() else pd.DataFrame(
        {"date": pd.to_datetime([]), "revenue": [], "channel": []})
    if "channel" not in rev.columns:
        rev["channel"] = "티스토리"  # 이전 기록은 티스토리 수익
    with st.expander("수익 입력"):
        a, b, ch, c = st.columns([2, 2, 2, 1])
        d = a.date_input("날짜")
        v = b.number_input("수익(원)", min_value=0.0, step=100.0)
        channel = ch.selectbox("채널", ["GitHub Pages", "티스토리", "기타(제휴 등)"])
        if c.button("추가"):
            rev = pd.concat([rev[~((rev["date"] == pd.Timestamp(d)) & (rev["channel"] == channel))],
                             pd.DataFrame({"date": [pd.Timestamp(d)], "revenue": [v], "channel": [channel]})]
                            ).sort_values("date")
            REVENUE_CSV.parent.mkdir(parents=True, exist_ok=True)
            rev.to_csv(REVENUE_CSV, index=False)
            st.rerun()
        up = st.file_uploader("CSV 업로드 (date,revenue[,channel])", type="csv")
        if up is not None:
            new = pd.read_csv(up, parse_dates=["date"])
            new["channel"] = new["channel"] if "channel" in new.columns else "GitHub Pages"
            rev = pd.concat([rev, new[["date", "revenue", "channel"]]]).drop_duplicates(
                ["date", "channel"], keep="last").sort_values("date")
            rev.to_csv(REVENUE_CSV, index=False)

    period = st.radio("집계 단위", ["일별", "월별", "분기별", "연도별"], horizontal=True)
    if rev.empty:
        st.info("입력된 수익 데이터가 없습니다. 애드센스 승인 후 입력하세요.")
    else:
        freq = {"일별": "D", "월별": "M", "분기별": "Q", "연도별": "Y"}[period]
        rule = {"M": "ME", "Q": "QE", "Y": "YE"}.get(freq, freq)
        agg = rev.pivot_table(index="date", columns="channel", values="revenue", aggfunc="sum").fillna(0)             .resample(rule).sum()
        agg.index = agg.index.to_period(freq).astype(str)
        last30 = rev[rev["date"] >= pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=30)]
        k = st.columns(4)
        k[0].metric("오늘 수익", f"{rev.loc[rev['date'] == pd.Timestamp(today), 'revenue'].sum():,.0f}원")
        k[1].metric(f"최근 {period[:-1]}", f"{agg.iloc[-1].sum():,.0f}원")
        k[2].metric("누적", f"{rev['revenue'].sum():,.0f}원")
        pv = (pages_perf.get("pv_30d") or 0)
        pages_rev = last30.loc[last30["channel"] == "GitHub Pages", "revenue"].sum()
        k[3].metric("Pages RPM (30일)", f"{pages_rev / pv * 1000:,.0f}원" if pv else "-")
        st.bar_chart(agg)

# ─────────────────────────── 설정 (한 번에 저장하는 폼) ───────────────────────────
with t_set:
    st.caption("변경 후 각 영역의 **저장** 버튼을 누르면 이 PC와 GitHub 자동 수집에 함께 반영됩니다.")

    def save(changes: dict, msg: str) -> None:
        core.save_config({**core.load_config(), **changes})
        with st.spinner("GitHub 에 반영 중…"):
            err = core.git_sync(["config.json"], f"chore(config): {msg} [skip ci]")
        if err:
            st.error(f"로컬 저장됨, GitHub 반영 실패: {err}")
        else:
            st.toast(f"✅ 저장됨 — {msg}")

    left, right = st.columns([3, 2])
    with left, st.form("collect"):
        st.subheader("📥 수집")
        c1, c2 = st.columns(2)
        interval = c1.selectbox("수집 주기", list(core.INTERVALS), index=list(core.INTERVALS).index(cfg["interval"]))
        max_items = c2.slider("1시간 이상 주기: 1회 수집 글 수", 5, 30, int(cfg["max_items"]))
        burst = c2.slider("'계속'·10분 주기: 1회 처리 글 수", 1, 10, int(cfg.get("burst_items", 3)))
        domains = c1.multiselect("수집 분야", list(core.DOMAINS), default=[d for d in cfg["domains"] if d in core.DOMAINS],
                                 format_func=lambda d: f"{core.DOMAIN_META.get(d, {}).get('icon', '📁')} {d}")
        c3, c4 = st.columns(2)
        save_notion = False  # 노션 저장은 종료 (GitHub 만 사용)
        publish = c4.toggle("티스토리 초안 생성", value=bool(cfg["publish"]))
        llm_budget = st.number_input("AI 하루 최대 호출 수", 50, 5000, int(cfg.get("llm_daily_budget", 500)), step=50,
                                     help="Gemini 무료 한도 보호 — AI Studio 에서 내 한도를 확인해 맞추세요.")
        if st.form_submit_button("💾 수집 설정 저장", type="primary", width="stretch"):
            if not domains:
                st.error("수집 분야를 하나 이상 선택하세요.")
            else:
                save({"interval": interval, "max_items": max_items, "burst_items": burst, "domains": domains,
                      "save_notion": save_notion, "publish": publish, "llm_daily_budget": llm_budget},
                     f"수집 설정 (주기 {interval})")

    with right, st.container(border=True):
        st.subheader("🧠 AI 사용량 예측")
        iv = INTERVAL_MIN.get(cfg["interval"], 60)
        items = cfg.get("burst_items", 3) if iv < 60 else cfg["max_items"]
        # 키워드는 AI 를 쓰지 않음 → 1회 = 글 요약(+주제 밖 여유) + 가이드·정리(3시간마다 약 2~3회)
        per_run = items * 1.3 + 4 * iv / 180
        need_day = per_run * max(1, 1440 // iv)
        budget, used = int(cfg.get("llm_daily_budget", 500)), core.llm_usage_today()
        fb, cap = core.llm_fallback_usage(), core.llm_capacity_left()
        st.progress(min(1.0, used / budget) if budget else 1.0,
                    text=f"Gemini {used} / {budget}회" + "".join(f" · 예비 {k} {v}회" for k, v in fb.items()))
        k1, k2, k3 = st.columns(3)
        k1.metric("오늘 남은 여력", f"{cap}회", help="Gemini 잔여 + 예비 AI(Groq 등) 잔여")
        k2.metric("1회 실행", f"≈{per_run:.0f}회")
        k3.metric("하루 필요", f"≈{need_day:,.0f}회")
        if cfg.get("auto_mode"):
            st.success("🤖 자동 모드: AI 관리자가 남은 여력에 맞춰 수집량을 조절하므로 한도로 멈추지 않습니다")
        elif cap >= need_day * (1 - (datetime.now().hour / 24)):
            st.success("남은 여력 안에서 오늘 계속 수집 가능")
        else:
            mins = int(cap // max(per_run, 1)) * iv
            eta = (datetime.now() + pd.Timedelta(minutes=mins)).strftime("%H:%M")
            st.warning(f"약 {mins // 60}시간 {mins % 60}분 뒤(≈{eta}) 여력 소진 → {core.llm_reset_kst()} 리셋 후 재개")
        st.caption(f"리셋: 매일 미국 태평양 자정 = 한국 {core.llm_reset_kst()[-5:]} · 사용량은 이 PC + GitHub 합산")

    a, b = st.columns(2)
    with a, st.form("mail"):
        st.subheader("✉️ 메일 알림")
        email_to = st.text_input("받는 주소", cfg["email_to"])
        email_per_day = st.number_input("하루 최대 수신 횟수", 0, 48, int(cfg["email_per_day"]))
        if st.form_submit_button("💾 메일 설정 저장", width="stretch"):
            save({"email_to": email_to, "email_per_day": email_per_day}, "메일 설정")
    with b, st.form("add_domain", clear_on_submit=True):
        st.subheader("➕ 수집 분야 추가")
        new_name = st.text_input("분야 이름", placeholder="예: 3D 프린팅, 모션캡처, XR·메타버스")
        n1, n2 = st.columns([1, 3])
        new_icon = n1.text_input("아이콘", value="📁", max_chars=4)
        new_about = n2.text_input("설명 (AI 분류 기준)", placeholder="3D printing hardware, slicers, materials")
        new_seeds = st.text_input("검색 키워드 (쉼표, 비우면 AI 추천)", placeholder="Bambu Lab, Prusa, resin printer")
        new_feeds = st.text_area("RSS 주소 (줄마다 하나, 선택)", height=68)
        if st.form_submit_button("➕ 분야 추가", width="stretch"):
            name = new_name.strip()[:30]
            if not name:
                st.error("분야 이름을 입력하세요.")
            elif name in core.DOMAINS or name in core.BUILTIN_DOMAINS:
                st.error("이미 있는 분야입니다.")
            else:
                seeds = [x.strip() for x in new_seeds.split(",") if x.strip()]
                if not seeds:
                    try:
                        seeds = core._parse_json(core.llm(
                            f'Field: {name} ({new_about}). Return JSON {{"keywords": [5 short English news search terms]}}',
                            max_tokens=120, json_mode=True)).get("keywords", [])[:6]
                    except Exception as ex:
                        st.warning(f"키워드 추천 실패 — 분야 이름으로 검색합니다: {ex}")
                ok_feeds = []
                for u in [x.strip() for x in new_feeds.splitlines() if x.strip()]:
                    try:
                        if core.fetch_feed(u).entries:
                            ok_feeds.append(u)
                    except Exception:
                        st.warning(f"읽을 수 없는 RSS 제외: {u}")
                custom = dict(cfg.get("custom_domains") or {})
                custom[name] = {"seeds": seeds or [name], "feeds": ok_feeds, "icon": new_icon.strip() or "📁",
                                "about": new_about.strip() or name}
                save({"custom_domains": custom, "domains": list(dict.fromkeys(cfg["domains"] + [name]))}, f"분야 추가 — {name}")

    custom_names = [k for k, v in (cfg.get("custom_domains") or {}).items() if not v.get("archived")]
    if custom_names:
        with st.expander("🗑️ 추가한 분야 보관(수집 중단, 게시판·글은 유지)"):
            del_name = st.selectbox("분야 선택", custom_names)
            if st.button(f"'{del_name}' 보관 처리"):
                custom = dict(cfg["custom_domains"])
                custom[del_name] = {**custom[del_name], "archived": True}
                save({"custom_domains": custom, "domains": [d for d in cfg["domains"] if d != del_name]}, f"분야 보관 — {del_name}")

    st.divider()
    st.subheader("⏰ 기한·알림 관리")
    st.caption("등록한 날짜가 다가오면 현황판 맨 위에 D-day 로 알려 줍니다 (14일 전부터 주황, 3일 전부터 빨강).")
    rems = list(cfg.get("reminders") or [])
    for i, r in enumerate(rems):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{r.get('title')}** · {r.get('date')}" + (f" · {r['note']}" if r.get("note") else ""))
        if c2.button("삭제", key=f"rem_del_{i}"):
            save({"reminders": rems[:i] + rems[i + 1:]}, f"기한 삭제 — {r.get('title')}")
            st.rerun()
    with st.form("reminder_add", clear_on_submit=True):
        r1, r2, r3 = st.columns([2, 1, 2])
        rt = r1.text_input("항목", placeholder="예: 도메인 갱신, 애드센스 심사, 토큰 재발급")
        rd = r2.date_input("날짜")
        rn = r3.text_input("메모 (선택)")
        if st.form_submit_button("➕ 기한 추가") and rt.strip():
            save({"reminders": rems + [{"title": rt.strip()[:40], "date": str(rd), "note": rn.strip()[:100]}]},
                 f"기한 추가 — {rt.strip()[:20]}")
            st.rerun()
    with st.form("token_exp"):
        cur_exp = cfg.get("gh_pat_expires") or ""
        st.markdown("**GitHub 토큰(GH_PAT) 만료일** — 인터넷 현황판에서는 자동으로 알아내 기록합니다. "
                    "이 PC 에서 직접 입력해도 됩니다.")
        te = st.date_input("만료일", value=datetime.fromisoformat(cur_exp).date() if cur_exp else None)
        if st.form_submit_button("저장") and te:
            save({"gh_pat_expires": str(te)}, "GitHub 토큰 만료일")
            st.rerun()

# ─────────────────────────── 오늘 (한눈에: 할 일 · 오늘 성과 · 무엇이 읽히나) ───────────────────────────
with t_today:
    import manager as _mgr
    plan_t = core._load_json(_mgr.PLAN_PATH, {})
    done_t = _mgr.done_today()
    st.subheader("✅ 결정할 일")
    pend = [x for x in _mgr.board()["proposals"] if x["status"] == "new" and (x.get("site") or "3dflowhub") == "3dflowhub"]
    if not pend:
        st.success("검토할 AI 관리자 제안이 없습니다")
    for x in pend[:5]:
        with st.container(border=True):
            st.markdown(f"**{x['title']}** · {x.get('category')} · 노력 {x.get('effort')}")
            st.caption("수락하면: " + _mgr.describe(x.get("action")))
            c1, c2, c3, _ = st.columns([1, 1, 1, 3])
            if c1.button("✅ 수락", key=f"t_acc_{x['id']}", type="primary", width="stretch"):
                _mgr.decide(x["id"], "accepted")
                save_manager("제안 수락")
                st.rerun()
            if c2.button("⏸ 보류", key=f"t_hold_{x['id']}", width="stretch"):
                _mgr.decide(x["id"], "held")
                save_manager("제안 보류")
                st.rerun()
            if c3.button("✕ 거절", key=f"t_rej_{x['id']}", width="stretch"):
                _mgr.decide(x["id"], "rejected")
                save_manager("제안 거절")
                st.rerun()

    todo_t = _mgr.manual_todo("3dflowhub")
    if todo_t:
        with st.expander(f"🛠 직접 작업 {len(todo_t)}건 — 요청문을 복사해 Claude 에게 맡기세요"):
            for x in todo_t:
                st.markdown(f"**{x['title']}**")
                st.code(_mgr.claude_request(x), language=None, wrap_lines=True)
                if st.button("✔ 완료", key=f"t_done_{x['id']}"):
                    _mgr.decide(x["id"], "done")
                    save_manager("직접 작업 완료")
                    st.rerun()

    import staff as _staff
    waiting = [x for x in _staff.outbox() if x["status"] == "new" and (x.get("site") or "3dflowhub") == "3dflowhub"]
    st.subheader(f"📣 홍보 대기함 ({len(waiting)})")
    st.caption("마케터가 쓴 초안입니다. 오른쪽 위 복사 아이콘으로 복사해 해당 채널에 올린 뒤 '게시함'을 눌러 주세요. "
               "링크에는 채널 표시가 붙어 있어 어디서 방문이 왔는지 집계됩니다. (자동 게시는 하지 않습니다)")
    if not waiting:
        st.info("대기 중인 홍보 글이 없습니다. 마케터는 하루 한 번 새 초안을 씁니다.")
    for x in waiting[:6]:
        with st.container(border=True):
            st.caption(f"{x.get('channel')} · {kst(x['at'])}")
            if x.get("title"):
                st.markdown(f"**{x['title']}**")
            img_path = core.ROOT / x["image"] if x.get("image") else None
            if img_path and img_path.exists():  # 디자이너가 만든 홍보 이미지
                i1, i2 = st.columns([1, 2])
                i1.image(str(img_path), width="stretch")
                i1.download_button("⬇ 이미지 받기", img_path.read_bytes(), file_name=img_path.name, mime="image/png",
                                   key=f"dl_{x['id']}")
                with i2:
                    st.code(f"{x['body']}\n\n{x['url']}", language=None, wrap_lines=True)
            else:
                st.code(f"{x['body']}\n\n{x['url']}", language=None, wrap_lines=True)
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("✅ 게시함", key=f"post_{x['id']}", type="primary", width="stretch"):
                _staff.set_outbox(x["id"], "posted")
                core.git_sync(["memory/outbox.json"], "chore(staff): 홍보 게시 [skip ci]")
                st.rerun()
            if b2.button("건너뛰기", key=f"skip_{x['id']}", width="stretch"):
                _staff.set_outbox(x["id"], "skipped")
                core.git_sync(["memory/outbox.json"], "chore(staff): 홍보 건너뜀 [skip ci]")
                st.rerun()

    st.subheader("📈 오늘 성과")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("오늘 올린 소식", f"{done_t['news']}건")
    q2.metric("오늘 기초 가이드", f"{done_t['guides']}개")
    q3.metric("오늘 도구별 정리", f"{done_t['roundups']}개")
    q4.metric("남은 AI 여력", f"{core.llm_capacity_left()}회", help=f"리셋 {core.llm_reset_kst()} (한국 시간)")
    st.caption(("🤖 자동 모드 켜짐 — AI 관리자가 배분 중" if cfg.get("auto_mode") else "자동 모드 꺼짐 (자동화·진화 탭에서 켜기)")
               + (f" · 배분 뉴스 {int(plan_t['alloc'].get('news', 0) * 100)}% · 가이드 {int(plan_t['alloc'].get('guides', 0) * 100)}%"
                  f" · 정리 {int(plan_t['alloc'].get('roundups', 0) * 100)}%" if plan_t.get("alloc") else ""))


    st.subheader("👀 무엇이 읽히나 (최근 30일)")
    pg = core._load_json(core.ROOT / "memory" / "performance.json", {}).get("pages") or {}
    kinds = pg.get("by_kind") or {}
    if kinds:
        kdf = pd.DataFrame({"조회수": {"📰 소식": kinds.get("news", 0), "📚 기초 가이드": kinds.get("guides", 0),
                                      "🧭 도구별 정리": kinds.get("roundups", 0), "🏠 홈·기타": kinds.get("other", 0)}})
        st.bar_chart(kdf, horizontal=True, height=200)
    else:
        st.caption("콘텐츠 종류별 조회수는 다음 방문 통계 수집(3시간마다) 후 표시됩니다")
    v1, v2 = st.columns(2)
    with v1, st.container(border=True):
        st.markdown("**많이 읽힌 기초 가이드**")
        top_l = sorted((pg.get("learn") or {}).values(), key=lambda v: -v["views"])[:5]
        for v in top_l:
            st.markdown(f"- {v['title'].replace(' - 3dflowhub', '')} · {v['views']}회")
        if not top_l:
            st.caption("아직 데이터 없음")
    with v2, st.container(border=True):
        st.markdown("**많이 읽힌 소식**")
        top_p = sorted((pg.get("posts") or {}).values(), key=lambda v: -v["views"])[:5]
        for v in top_p:
            st.markdown(f"- {v['title'].replace(' - 3dflowhub', '')} · {v['views']}회")
        if not top_p:
            st.caption("아직 데이터 없음")
