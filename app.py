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
    domains = [d for d in core.DOMAINS
               if st.checkbox(f"{core.DOMAIN_META.get(d, {}).get('icon', '📁')} {d}", value=d in cfg["domains"], key=f"dom_{d}")]

    with st.expander("➕ 수집 분야 추가 / 삭제"):
        new_name = st.text_input("분야 이름", placeholder="예: 3D 프린팅, 모션캡처, XR·메타버스")
        new_icon = st.text_input("아이콘 (이모지)", value="📁", max_chars=4)
        new_about = st.text_input("설명 (AI 분류 기준)", placeholder="예: 3D printing hardware, slicers, materials")
        new_seeds = st.text_input("검색 키워드 (쉼표로 구분, 비우면 AI 가 추천)", placeholder="Bambu Lab, Prusa, resin printer")
        new_feeds = st.text_area("RSS 주소 (줄마다 하나, 선택)", placeholder="https://example.com/feed/", height=80)
        if st.button("➕ 분야 추가 (GitHub 반영)"):
            name = new_name.strip()[:30]  # core 의 이름 길이 제한과 동일 (불일치 시 수집에서 빠짐)
            if not name:
                st.error("분야 이름을 입력하세요.")
            elif name in core.DOMAINS or name in core.BUILTIN_DOMAINS:
                st.error("이미 있는 분야입니다.")
            else:
                seeds = [s.strip() for s in new_seeds.split(",") if s.strip()]
                if not seeds:  # AI 가 영어 검색 키워드 추천
                    try:
                        seeds = core._parse_json(core.llm(
                            f'Field: {name} ({new_about}). Return JSON {{"keywords": [5 short English news search terms]}}',
                            max_tokens=120, json_mode=True)).get("keywords", [])[:6]
                    except Exception as ex:
                        st.warning(f"키워드 추천 실패 — 분야 이름으로 검색합니다: {ex}")
                ok_feeds, bad_feeds = [], []
                for u in [x.strip() for x in new_feeds.splitlines() if x.strip()]:
                    try:
                        (ok_feeds if core.fetch_feed(u).entries else bad_feeds).append(u)
                    except Exception:
                        bad_feeds.append(u)
                custom = dict(cfg.get("custom_domains") or {})
                custom[name] = {"seeds": seeds or [name], "feeds": ok_feeds, "icon": new_icon.strip() or "📁",
                                "about": new_about.strip() or name}
                core.save_config({**core.load_config(), "custom_domains": custom,
                                  "domains": list(dict.fromkeys(cfg["domains"] + [name]))})
                err = core.git_sync(["config.json"], f"chore(config): 수집 분야 추가 — {name}")
                if bad_feeds:
                    st.warning("읽을 수 없는 RSS 는 제외했습니다: " + ", ".join(bad_feeds))
                st.error(err) if err else st.success(f"'{name}' 추가 완료 (키워드: {', '.join(seeds or [name])}). "
                                                     "다음 수집부터 반영되고 사이트에 게시판이 생깁니다.")
                st.rerun()
        custom_names = [k for k, v in (cfg.get("custom_domains") or {}).items() if not v.get("archived")]
        if custom_names:
            st.divider()
            del_name = st.selectbox("추가한 분야 삭제", ["선택…"] + custom_names)
            if del_name != "선택…" and st.button(f"🗑️ '{del_name}' 삭제 (이미 수집된 글은 유지)"):
                custom = dict(cfg["custom_domains"])  # 보관 처리: 수집 중단, 게시판·기존 글 주소는 유지
                custom[del_name] = {**custom[del_name], "archived": True}
                core.save_config({**core.load_config(), "custom_domains": custom,
                                  "domains": [d for d in cfg["domains"] if d != del_name]})
                err = core.git_sync(["config.json"], f"chore(config): 수집 분야 삭제 — {del_name}")
                st.error(err) if err else st.success(f"'{del_name}' 삭제됨")
                st.rerun()
    publish = st.toggle("티스토리 발행", value=cfg["publish"])

    st.header("✉️ 메일 알림")
    email_to = st.text_input("받는 주소", cfg["email_to"])
    email_per_day = st.number_input("하루 최대 수신 횟수", 0, 48, int(cfg["email_per_day"]))

    st.header("💾 저장 위치")
    save_notion = st.toggle("노션에도 저장", value=bool(cfg.get("save_notion", True)),
                            help="끄면 GitHub(게시판 사이트)에만 저장합니다. 노션 API 호출이 없어져 수집이 더 빠르고 단순해집니다.")

    st.header("🧠 AI 사용량")
    llm_budget = st.number_input("LLM 하루 최대 호출 수", 50, 5000, int(cfg.get("llm_daily_budget", 500)), step=50,
                                 help="Gemini 무료 한도 보호. AI Studio(aistudio.google.com) 에서 내 프로젝트 한도를 확인해 맞추세요.")
    burst = st.slider("'계속'·10분 모드 1회 처리 글 수", 1, 10, int(cfg.get("burst_items", 3)))

    # ── 소진 예측 ────────────────────────────────────────────
    interval_min = {"계속": 10, "10분 단위": 10, "1시간 단위": 60, "하루 단위": 1440, "1주일 단위": 10080}.get(interval, 60)
    items = burst if interval_min < 60 else max_items
    per_run = items + len(domains) + (2 * interval_min / 360) + (interval_min / 1440)  # 요약 + 키워드 + 성찰·정제
    runs_per_day = max(1, 1440 // interval_min)
    need_day = per_run * runs_per_day
    used = core.llm_usage_today()
    remaining = max(0, llm_budget - used)
    st.progress(min(1.0, used / llm_budget) if llm_budget else 1.0,
                text=f"오늘 {used} / {llm_budget}회 사용 (남은 {remaining}회)")
    m1, m2 = st.columns(2)
    m1.metric("1회 실행", f"약 {per_run:.0f}회")
    m2.metric("하루 필요", f"약 {need_day:,.0f}회")
    if need_day <= llm_budget:
        st.success(f"하루 한도 안에서 계속 수집 가능 (여유 {llm_budget - need_day:,.0f}회)")
    else:
        runs_left = int(remaining // per_run) if per_run else 0
        mins = runs_left * interval_min
        eta = (datetime.now() + pd.Timedelta(minutes=mins)).strftime("%H:%M")
        st.warning(f"현재 설정이면 약 {mins // 60}시간 {mins % 60}분 뒤(≈{eta}) 오늘 한도 소진 → "
                   f"이후 다음 날(오전 9시, 한국시간)까지 수집 중단")
        st.caption(f"하루 내내 돌리려면: 한도 {need_day:,.0f}회 이상, 또는 1회 {max(1, int(llm_budget / runs_per_day - len(domains)))}건 이하")
    st.caption("사용량은 이 PC + GitHub 합산 (마지막 동기화 기준)")

    if st.button("💾 설정 저장 (GitHub 반영)", use_container_width=True):
        core.save_config({**core.load_config(), "interval": interval, "max_items": max_items, "domains": domains,
                          "publish": publish, "email_to": email_to, "email_per_day": email_per_day,
                          "llm_daily_budget": llm_budget, "burst_items": burst, "save_notion": save_notion})
        with st.spinner("GitHub 에 반영 중…"):
            err = core.git_sync(["config.json"], f"chore(config): 대시보드 설정 변경 (주기 {interval}) [skip ci]")
        if err:
            st.error(f"로컬에는 저장됐지만 GitHub 반영 실패: {err}")
        else:
            st.success(f"저장 완료 — GitHub 자동 수집에도 반영됨 (주기: {interval}, 노션 {'저장' if save_notion else '안 함'})")

    st.caption("※ '계속'은 GitHub cron 최소 간격(10분)으로 실행됩니다.")

# ─────────────────────────── 수동 실행 ───────────────────────────
st.title("🧊 3dflowhub 큐레이션 현황판")
st.markdown("🌐 **게시판 사이트(GitHub Pages)**: [heo-j-h.github.io/3dflowhub](https://heo-j-h.github.io/3dflowhub/)  ·  "
            "📝 [티스토리](https://hjh1014.tistory.com/)  ·  🗂️ [노션 DB](https://app.notion.com/p/eba32801b6b141e2849ce85f819c3ea4)")

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
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"이미지": st.column_config.ImageColumn(width="small"),
                                    "원문": st.column_config.LinkColumn(),
                                    "사이트": st.column_config.LinkColumn(display_text="게시판 보기"),
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
            st.error(err) if err else st.success("저장됨 — 다음 사이트 배포부터 적용됩니다.")

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
