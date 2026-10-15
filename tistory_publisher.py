"""
티스토리 브라우저 자동 발행 (Open API 종료 대안)
================================================
이 PC 전용입니다. 로그인 정보는 저장하지 않고, 직접 로그인한 브라우저 프로필(.tistory_profile/)을 재사용합니다.

  1) 최초 1회 로그인:      python tistory_publisher.py --login
     → 크롬 창에서 카카오 계정으로 직접 로그인 후 창을 닫으세요.
  2) 테스트(발행 안 함):   python tistory_publisher.py --dry-run
     → 가장 최근 초안을 에디터에 채우고 스크린샷만 저장 (output/tistory_shots/)
  3) 초안 일괄 발행:       python tistory_publisher.py --publish [--public]
     → output/tistory_drafts/*.html 을 발행. 기본은 비공개, --public 시 공개 발행.

주의: 티스토리 에디터 화면이 바뀌면 선택자(SELECTORS) 수정이 필요할 수 있습니다.
     자동화 발행은 티스토리 운영정책(과도한 자동 게시 제한)을 지키도록 글 사이에 간격을 둡니다.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

import core

ROOT = Path(__file__).parent
PROFILE = ROOT / ".tistory_profile"
COOKIES = PROFILE / "session_cookies.json"  # 세션 쿠키는 브라우저 재시작 시 사라지므로 별도 저장
SHOTS = ROOT / "output" / "tistory_shots"
DONE_DIR = core.DRAFT_DIR / "published"
BLOG = core.TISTORY_BLOG_NAME
NEWPOST = f"https://{BLOG}.tistory.com/manage/newpost/?type=post"
GAP_SECONDS = (90, 240)  # 연속 발행 간격(초) 범위 — 일정 간격은 자동화로 보이기 쉬워 무작위
DAILY_LIMIT = int(__import__("os").getenv("TISTORY_DAILY_LIMIT", "3"))  # 하루 최대 발행 수 (저품질 판정 예방)
PUBLISH_LOG = ROOT / "memory" / "tistory_publish_log.json"


def published_today() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in core._load_json(PUBLISH_LOG, []) if r.get("at", "").startswith(today))


def _log_publish(entry: dict) -> None:
    rows = core._load_json(PUBLISH_LOG, [])
    rows.append({**entry, "at": datetime.now().isoformat(timespec="seconds")})
    core._save_json(PUBLISH_LOG, rows[-500:])

SELECTORS = {
    "title": "#post-title-inp",
    "mode_btn": "#editor-mode-layer-btn-open",
    "mode_html": "#editor-mode-html",
    "tag": "#tagText",
    "category_btn": "#category-btn",
    "complete": "#publish-layer-btn",
    "private": "#open0",
    "public": "#open20",
    "publish": "#publish-btn",
}


def _launch(p, headless: bool):
    """설치된 크롬 → 엣지 → Playwright 내장 크로미움 순으로 시도."""
    last = None
    for channel in ("chrome", "msedge", None):
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), channel=channel, headless=headless,
                viewport={"width": 1400, "height": 1000}, locale="ko-KR")
            break
        except Exception as e:
            last = e
    else:
        raise last
    if COOKIES.exists():
        ctx.add_cookies(json.loads(COOKIES.read_text(encoding="utf-8")))
    return ctx


def login() -> None:
    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tistory.com/auth/login?redirectUrl=" + NEWPOST, wait_until="domcontentloaded")
        print("브라우저에서 직접 로그인하세요. 로그인이 확인되면 창이 자동으로 닫힙니다(최대 10분).", flush=True)
        # 창을 직접 닫으면 쿠키가 디스크에 기록되기 전에 종료될 수 있어, 로그인 감지 후 정상 종료
        deadline = time.time() + 600
        ok = False
        while time.time() < deadline and ctx.pages:  # 창을 모두 닫으면 종료
            urls = [pg.url for pg in ctx.pages]
            # 로그인 후 블로그/관리 화면 등 tistory 페이지로 돌아오면 성공 (카카오 화면·로그인 화면 제외)
            if any("tistory.com" in u and "auth/login" not in u and "kakao" not in u for u in urls):
                ok = True
                break
            ctx.pages[0].wait_for_timeout(2000)  # time.sleep 은 Playwright 이벤트 처리를 막아 URL 이 갱신되지 않음
        if ok:
            page = ctx.pages[-1]
            page.goto(NEWPOST, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            ok = "/manage/" in page.url and "login" not in page.url
            print("현재 화면:", page.url, flush=True)
            if ok:
                COOKIES.write_text(json.dumps(ctx.cookies(), ensure_ascii=False), encoding="utf-8")
        ctx.close()
    print("로그인 세션 저장 완료" if ok else "로그인이 확인되지 않았습니다", flush=True)


def is_logged_in(page: Page) -> bool:
    page.goto(NEWPOST, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    return "/manage/" in page.url and "login" not in page.url


def parse_draft(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"<!-- TITLE: (.*?) \| TAGS: (.*?)(?: \| CATEGORY: (.*?))?(?: \| NOTION: (.*?))? -->\n", raw)
    if not m:
        return {"title": path.stem, "tags": [], "category": ("", ""), "notion_id": "", "html": raw, "path": path}
    domain, _, sub = (m.group(3) or "").partition("/")
    return {"title": m.group(1), "tags": [t for t in m.group(2).split(",") if t],
            "category": (domain.strip(), sub.strip()), "notion_id": (m.group(4) or "").strip(),
            "html": raw[m.end():], "path": path}


# ─────────────────────────── 카테고리 (도메인 > 세부) ───────────────────────────
CATEGORY_PAGE = f"https://{BLOG}.tistory.com/manage/category"


def _bundle(page: Page, name: str, parent=None):
    """이름이 name 인 카테고리 묶음(.bundle_item). parent 가 있으면 그 안의 하위 항목에서 찾는다."""
    scope = parent or page.locator("#category-app")
    loc = scope.locator(".bundle_item").filter(
        has=page.locator(".txt_name", has_text=re.compile(rf"^\s*{re.escape(name)}\s*$")))
    return loc.last if loc.count() else None


def _add_category(page: Page, name: str, parent=None) -> None:
    if parent is None:
        page.locator("input[value='카테고리 추가']").dispatch_event("click")
    else:  # 상위 카테고리 행의 '추가' → 하위 카테고리
        parent.locator(".basic_item").first.locator("a.btn_post", has_text="추가").first.dispatch_event("click")
    page.wait_for_timeout(500)
    form = page.locator("form.edit_item").last
    form.locator("input.tf_blog").fill(name)
    form.get_by_text("확인", exact=True).dispatch_event("click")
    page.wait_for_timeout(700)


def ensure_categories(page: Page, pairs: set[tuple[str, str]]) -> list[str]:
    """티스토리에 '도메인 > 세부' 카테고리가 없으면 자동 생성. 생성한 이름 목록 반환."""
    page.goto(CATEGORY_PAGE, wait_until="domcontentloaded")
    page.wait_for_selector("#category-app", timeout=20000)
    page.wait_for_timeout(1500)
    created = []
    for domain, sub in sorted(pairs):
        if not domain:
            continue
        top = _bundle(page, domain)
        if top is None:
            _add_category(page, domain)
            created.append(domain)
            top = _bundle(page, domain)
        if sub and top is not None and _bundle(page, sub, parent=top) is None:
            _add_category(page, sub, parent=top)
            created.append(f"{domain} > {sub}")
    if created:
        page.get_by_text("변경사항 저장", exact=True).first.dispatch_event("click")  # 카테고리 관리 영역 저장
        page.wait_for_timeout(2500)
    return created


def select_category(page: Page, domain: str, sub: str) -> str:
    """에디터 카테고리 드롭다운에서 세부 → 도메인 순으로 선택."""
    page.click(SELECTORS["category_btn"])
    page.wait_for_selector("#category-list [role=option]", timeout=5000)
    options = page.locator("#category-list [role=option]")
    labels = [options.nth(i).get_attribute("aria-label") or "" for i in range(options.count())]
    for want in (sub, domain):
        for i, label in enumerate(labels):
            if want and label.strip().lstrip("-ㄴ ").strip() == want:
                options.nth(i).click()
                return label
    page.keyboard.press("Escape")
    return ""


def fill_post(page: Page, post: dict) -> None:
    page.on("dialog", lambda d: d.accept())  # 'HTML 모드로 전환' 확인창 등 자동 수락
    page.goto(NEWPOST, wait_until="domcontentloaded")
    page.wait_for_selector(SELECTORS["title"], timeout=20000)
    # 이전 임시저장 글 이어쓰기 팝업이 뜨면 '취소'
    try:
        page.get_by_role("button", name="취소").click(timeout=2000)
    except PWTimeout:
        pass

    # HTML 모드로 전환 후 CodeMirror 에 본문 주입
    page.click(SELECTORS["mode_btn"])
    page.click(SELECTORS["mode_html"])
    page.wait_for_selector(".CodeMirror", timeout=10000)
    page.evaluate("html => document.querySelector('.CodeMirror').CodeMirror.setValue(html)", post["html"])

    page.fill(SELECTORS["title"], post["title"])
    post["category_selected"] = select_category(page, *post["category"]) if any(post["category"]) else ""
    for t in post["tags"][:10]:
        page.fill(SELECTORS["tag"], t)
        page.keyboard.press("Enter")


def publish(page: Page, public: bool) -> str:
    page.click(SELECTORS["complete"])
    page.wait_for_selector(SELECTORS["publish"], timeout=10000)
    page.click(SELECTORS["public"] if public else SELECTORS["private"])
    page.click(SELECTORS["publish"])
    page.wait_for_url(re.compile(r"/manage/posts"), timeout=30000)
    page.wait_for_timeout(2000)
    # 글 관리 목록 첫 글(방금 발행한 글)의 실제 주소
    link = page.locator(f"a[href*='{BLOG}.tistory.com/']").filter(has_not_text="글쓰기").first
    try:
        href = link.get_attribute("href", timeout=5000) or ""
        if re.search(r"tistory\.com/(\d+|entry/)", href):
            return href
    except PWTimeout:
        pass
    return page.url


def shot(page: Page, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def run(dry_run: bool, public: bool, limit: int, headless: bool) -> list[dict]:
    drafts = sorted(core.DRAFT_DIR.glob("*.html"))[:limit] if core.DRAFT_DIR.exists() else []
    if not drafts:
        print("발행할 초안이 없습니다:", core.DRAFT_DIR)
        return []
    results = []
    with sync_playwright() as p:
        ctx = _launch(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not is_logged_in(page):
            ctx.close()
            raise SystemExit("로그인이 필요합니다: python tistory_publisher.py --login")
        remaining = max(0, DAILY_LIMIT - published_today())
        if not dry_run and remaining == 0:
            ctx.close()
            print(f"오늘 발행 한도({DAILY_LIMIT}개)에 도달했습니다. 내일 다시 실행하세요.")
            return []
        targets = drafts[:1] if dry_run else drafts[:remaining]
        if not dry_run:  # 필요한 카테고리 자동 생성 (테스트 모드에서는 블로그를 변경하지 않음)
            pairs = {parse_draft(pth)["category"] for pth in targets}
            try:
                created = ensure_categories(page, pairs)
                print("카테고리 생성:", created or "없음", flush=True)
            except Exception as e:
                print("카테고리 생성 실패(카테고리 없이 진행):", str(e)[:200], flush=True)
        for i, path in enumerate(targets):
            post = parse_draft(path)
            try:
                fill_post(page, post)
                if dry_run:
                    results.append({"title": post["title"], "status": "dry_run",
                                    "category": post.get("category_selected"), "shot": shot(page, "dry_run")})
                    print(json.dumps(results[-1], ensure_ascii=False))
                    continue
                url = publish(page, public)
                if post["notion_id"]:  # 노션 상태 Published + 티스토리 주소 기록
                    core.mark_notion_published(core._notion(), post["notion_id"], url)
                DONE_DIR.mkdir(parents=True, exist_ok=True)
                path.rename(DONE_DIR / path.name)
                results.append({"title": post["title"], "status": "published",
                                "category": post.get("category_selected"), "url": url})
                _log_publish(results[-1])
            except Exception as e:  # 한 글 실패가 전체를 멈추지 않도록
                results.append({"title": post["title"], "status": "error", "error": str(e)[:300],
                                "shot": shot(page, "error")})
            print(json.dumps(results[-1], ensure_ascii=False))
            if not dry_run and i < len(targets) - 1:
                time.sleep(__import__("random").uniform(*GAP_SECONDS))
        ctx.close()
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="에디터에 채우고 스크린샷만 (발행 안 함)")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--public", action="store_true", help="공개 발행 (기본 비공개)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--show", action="store_true", help="브라우저 창 보이기")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.dry_run or a.publish:
        run(a.dry_run, a.public, a.limit, headless=not a.show)
    else:
        ap.print_help()
