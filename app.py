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
import streamlit.components.v1 as _components  # noqa: E402
_components.html("""<script>
const d = window.parent.document;
d.documentElement.lang = "ko";
d.documentElement.setAttribute("translate", "no");
d.documentElement.classList.add("notranslate");
if (!d.querySelector('meta[name="google"]')) {
  const m = d.createElement("meta"); m.name = "google"; m.content = "notranslate"; d.head.appendChild(m);
}
</script>""", height=0)
REVENUE_CSV = Path(core.ROOT) / "memory" / "revenue.csv"
GH_REPO = os.getenv("GH_REPO", "HEO-J-H/3dflowhub")
GH_PAT = os.getenv("GH_PAT", "")  # workflow_dispatch 원격 트리거용 (repo: actions write)
SITE_URL = "https://heo-j-h.github.io/3dflowhub/"
INTERVAL_MIN = {"계속": 10, "10분 단위": 10, "1시간 단위": 60, "하루 단위": 1440, "1주일 단위": 10080}

# 화면 스타일: 게시판 사이트와 같은 톤 (카드·여백·위계)
st.markdown("""<style>
[data-testid="stMetric"]{background:var(--secondary-background-color);border-radius:16px;padding:14px 18px}
[data-testid="stMetricLabel"] p{font-size:13px;opacity:.75}
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
    try:
        r = requests.get(f"https://api.github.com/repos/{GH_REPO}/actions/runs?per_page=20", timeout=10)
        return r.json().get("workflow_runs", [])
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
    color = "#30d158" if ok else "#ff453a"
    st.markdown(f'<span class="status-dot" style="background:{color}"></span>**자동 수집 '
                f'{"정상" if ok else "확인 필요"}**', unsafe_allow_html=True)
    st.caption(f"주기 {cfg['interval']} · 마지막 수집 {ago(last.get('at', ''))} "
               f"(수집 {last.get('collected', 0)} → 저장 {last.get('saved', 0)})")
    used, budget = core.llm_usage_today(), int(cfg.get("llm_daily_budget", 500))
    q = core.llm_quota_status()
    st.progress(1.0 if q["exhausted"] else min(1.0, used / budget) if budget else 1.0,
                text=f"AI 사용 {used}/{budget}회" + (" · 한도 소진(16~17시 리셋)" if q["exhausted"] else ""))
    if q["learned_limit"] and q["learned_limit"] < budget:
        st.caption(f"⚠️ 실제 Gemini 한도 약 {q['learned_limit']}회 — 설정값을 낮추세요")
    pages = [r for r in runs if r["name"].endswith("pages")]
    if pages:
        st.caption(f"사이트 배포 {ago(pages[0]['created_at'])} · {'✅' if pages[0]['conclusion'] == 'success' else '⏳' if pages[0]['conclusion'] is None else '❌'}")


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


with st.sidebar:
    st.markdown("### 🧊 3dflowhub")
    status_panel()
    st.divider()
    left = core.llm_budget_left()
    if st.button("🚀 지금 바로 수집", type="primary", disabled=job["running"] or left <= 0,
                 use_container_width=True,
                 help="이 PC에서 현재 설정으로 즉시 수집합니다 (GitHub 자동 수집과 별개)"):
        job.update(running=True, result=None, error=None)
        threading.Thread(target=_run_local, daemon=True,
                         args=(job, {"max_items": cfg["max_items"], "domains": cfg["domains"],
                                     "publish": cfg["publish"]})).start()
        st.rerun()
    if left <= 0 and not job["running"]:
        st.caption(f"⏸ AI 일일 한도 소진 — {core.llm_reset_kst()}(한국시간)에 다시 켜집니다")
    job_panel()
    if GH_PAT and st.button("☁️ GitHub에서 실행", use_container_width=True):
        r = requests.post(f"https://api.github.com/repos/{GH_REPO}/actions/workflows/auto_curation.yml/dispatches",
                          headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
                          json={"ref": "main", "inputs": {}}, timeout=20)
        st.toast("GitHub 실행 요청 완료" if r.status_code == 204 else f"요청 실패 {r.status_code}")
    if st.button("🔄 데이터 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.link_button("🌐 게시판 사이트", SITE_URL, use_container_width=True)
    st.link_button("📝 티스토리", "https://hjh1014.tistory.com/", use_container_width=True)
    st.link_button("⚙️ GitHub Actions", f"https://github.com/{GH_REPO}/actions", use_container_width=True)

# ─────────────────────────── 본문 ───────────────────────────
st.title("큐레이션 현황판")
df = load_rows()
today = datetime.now().strftime("%Y-%m-%d")
if not df.empty:
    df["수집일"] = pd.to_datetime(df["수집일"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul")

t_home, t_list, t_auto, t_draft, t_rev, t_set = st.tabs(
    ["📊 개요", "📰 글 목록", "🧬 자동화·진화", "📝 티스토리", "💰 수익·방문", "🛠 설정"])

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
                    st.image(r["이미지"], use_container_width=True)
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
                   "이 선택은 AI 수집 전략 학습에도 반영됩니다.")
        edited = st.data_editor(
            view, use_container_width=True, hide_index=True, key="curate",
            disabled=[c for c in view.columns if c not in ("추천", "숨김")],
            column_order=["추천", "숨김"] + [c for c in view.columns if c not in ("추천", "숨김", "ID")],
            column_config={"추천": st.column_config.CheckboxColumn("✅ 추천", width="small"),
                           "숨김": st.column_config.CheckboxColumn("🚫 숨김", width="small"),
                           "이미지": st.column_config.ImageColumn(width="small"),
                           "원문": st.column_config.LinkColumn(),
                           "사이트": st.column_config.LinkColumn(display_text="게시판 보기"),
                           "티스토리": st.column_config.LinkColumn(),
                           "수집일": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
        if "ID" in view.columns:
            changes = {}
            for (_, a), (_, b) in zip(view.iterrows(), edited.iterrows()):
                if (a["추천"], a["숨김"]) != (b["추천"], b["숨김"]):
                    changes[b["ID"]] = "hide" if b["숨김"] else "pick" if b["추천"] else ""
            if changes and st.button(f"💾 선택 {len(changes)}건 저장 · 사이트에 반영", type="primary"):
                core.set_curation(changes)
                err = core.git_sync(["memory/curation.json"], "chore(curation): 에디터 추천/숨김")
                if err:
                    st.error(f"로컬 저장됨, GitHub 반영 실패: {err}")
                else:
                    st.toast("✅ 저장됨 — 다음 사이트 배포부터 반영됩니다")
                st.cache_data.clear()

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
        errs = [x for x in last.get("errors", []) if "news.google.com" not in x]  # 구글 뉴스 0건은 정상
        skips = {"short body": "본문이 너무 짧아 건너뜀", "off-topic": "주제와 무관해 건너뜀",
                 "prefiltered": "3D 관련 어휘가 없어 AI 요약 전에 제외"}
        info = {k: errs.count(k) for k in skips if k in errs}
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
                                   for k, v in top]), use_container_width=True, hide_index=True,
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
                         use_container_width=True, hide_index=True,
                         column_config={"주소": st.column_config.LinkColumn()})
        st.caption(f"수집: {latest.get('at', '-')}")

    st.divider()
    # ── 3) 광고 수익 (채널별) ──────────────────────────────────
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
        save_notion = c3.toggle("노션에도 저장", value=bool(cfg.get("save_notion", True)))
        publish = c4.toggle("티스토리 초안 생성", value=bool(cfg["publish"]))
        llm_budget = st.number_input("AI 하루 최대 호출 수", 50, 5000, int(cfg.get("llm_daily_budget", 500)), step=50,
                                     help="Gemini 무료 한도 보호 — AI Studio 에서 내 한도를 확인해 맞추세요.")
        if st.form_submit_button("💾 수집 설정 저장", type="primary", use_container_width=True):
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
        per_run = items + len(cfg["domains"]) + (2 * iv / 360) + (iv / 1440)
        need_day = per_run * max(1, 1440 // iv)
        budget, used = int(cfg.get("llm_daily_budget", 500)), core.llm_usage_today()
        st.progress(min(1.0, used / budget) if budget else 1.0, text=f"오늘 {used} / {budget}회 (남은 {max(0, budget - used)}회)")
        k1, k2 = st.columns(2)
        k1.metric("1회 실행", f"≈{per_run:.0f}회")
        k2.metric("하루 필요", f"≈{need_day:,.0f}회")
        if need_day <= budget:
            st.success(f"하루 한도 안에서 계속 수집 가능 (여유 {budget - need_day:,.0f}회)")
        else:
            mins = int(max(0, budget - used) // per_run) * iv
            eta = (datetime.now() + pd.Timedelta(minutes=mins)).strftime("%H:%M")
            st.warning(f"약 {mins // 60}시간 {mins % 60}분 뒤(≈{eta}) 오늘 한도 소진 → 다음 날 오전 9시까지 중단")
        st.caption("저장된 설정 기준 · 사용량은 이 PC + GitHub 합산")

    a, b = st.columns(2)
    with a, st.form("mail"):
        st.subheader("✉️ 메일 알림")
        email_to = st.text_input("받는 주소", cfg["email_to"])
        email_per_day = st.number_input("하루 최대 수신 횟수", 0, 48, int(cfg["email_per_day"]))
        if st.form_submit_button("💾 메일 설정 저장", use_container_width=True):
            save({"email_to": email_to, "email_per_day": email_per_day}, "메일 설정")
    with b, st.form("add_domain", clear_on_submit=True):
        st.subheader("➕ 수집 분야 추가")
        new_name = st.text_input("분야 이름", placeholder="예: 3D 프린팅, 모션캡처, XR·메타버스")
        n1, n2 = st.columns([1, 3])
        new_icon = n1.text_input("아이콘", value="📁", max_chars=4)
        new_about = n2.text_input("설명 (AI 분류 기준)", placeholder="3D printing hardware, slicers, materials")
        new_seeds = st.text_input("검색 키워드 (쉼표, 비우면 AI 추천)", placeholder="Bambu Lab, Prusa, resin printer")
        new_feeds = st.text_area("RSS 주소 (줄마다 하나, 선택)", height=68)
        if st.form_submit_button("➕ 분야 추가", use_container_width=True):
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
