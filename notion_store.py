"""Notion 저장소 (선택 기능). config.json 의 save_notion=true 이고 NOTION_TOKEN 이 있을 때만 쓰인다.
기본 운영은 GitHub(content/posts) 전용 — core 는 클라이언트가 None 이면 이 모듈을 불러오지도 않는다."""
from __future__ import annotations

import core

NOTION_SCHEMA = {
    "URL": {"url": {}},
    "Domain": {"select": {"options": [{"name": d} for d in core.DOMAINS]}},
    "Category": {"select": {}},
    "Tags": {"multi_select": {}},
    "Summary": {"rich_text": {}},
    "Thumbnail": {"files": {}},
    "Video": {"url": {}},
    "Status": {"select": {"options": [{"name": "Collected", "color": "gray"},
                                      {"name": "Published", "color": "green"}]}},
    "TistoryURL": {"url": {}},
    "CollectedAt": {"date": {}},
    "Views": {"number": {}},
}


def ensure_notion_schema(client) -> None:
    """DB에 필요한 속성이 없으면 자동 생성하고, 제목 속성 이름을 'Name'으로 맞춘다."""
    if client is None:
        return
    try:
        # 스키마 변경은 최신 data source API(2025-09-03)로 해야 실제 반영된다
        new = core.NotionClient(auth=core.NOTION_TOKEN)
        ds_id = new.databases.retrieve(database_id=core.NOTION_DATABASE_ID)["data_sources"][0]["id"]
        props = new.request(path=f"data_sources/{ds_id}", method="GET")["properties"]
        update: dict = {}
        title_name = next((n for n, p in props.items() if p["type"] == "title"), None)
        if title_name and title_name != "Name":
            update[title_name] = {"name": "Name"}
        for name, spec in NOTION_SCHEMA.items():
            if name not in props:
                update[name] = spec
            elif props[name]["type"] != next(iter(spec)):
                core.log.warning("Notion 속성 '%s' 타입이 %s 입니다 (필요: %s) — 직접 수정 필요",
                            name, props[name]["type"], next(iter(spec)))
        if update:
            new.request(path=f"data_sources/{ds_id}", method="PATCH", body={"properties": update})
            core.log.info("Notion DB 속성 생성/수정: %s", ", ".join(update))
    except Exception as e:
        core.log.error("Notion 스키마 설정 실패 (통합 연결 여부 확인): %s", e)


def _query_db(client, body: dict) -> dict:
    # notion-client 2.7+ 에서 databases.query 가 제거되어 REST 직접 호출
    return client.request(path=f"databases/{core.NOTION_DATABASE_ID}/query", method="POST", body=body)


def notion_existing_urls(client) -> set[str]:
    """Notion DB에 이미 있는 URL 해시 (중복 방지 1차)."""
    seen, cursor = set(), None
    try:
        while True:
            res = _query_db(client, {"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            for p in res["results"]:
                u = p["properties"].get("URL", {}).get("url")
                if u:
                    seen.add(core.url_hash(u))
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
    except Exception as e:
        core.log.warning("Notion 조회 실패: %s", e)
    return seen


def _rt(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[:1990]}}]


def save_to_notion(client, item: dict) -> str | None:
    """Notion DB 속성: Name(title) URL(url) Domain(select) Tags(multi_select)
    Summary(rich_text) Status(select) TistoryURL(url) CollectedAt(date)"""
    if client is None:
        return None
    media = item.get("media") or {}
    children = []
    if media.get("image"):
        children.append({"object": "block", "type": "image",
                         "image": {"type": "external", "external": {"url": media["image"]}}})
    if media.get("video"):
        children.append({"object": "block", "type": "video",
                         "video": {"type": "external", "external": {"url": media["video"]}}})
    if item.get("insight"):
        children.append({"object": "block", "type": "callout",
                         "callout": {"rich_text": _rt(item["insight"]), "icon": {"type": "emoji", "emoji": "💡"}}})
    for s in item["sections"]:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rt(s["heading"])}})
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(s["body"])}})
    faq = [f for f in item.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")]
    if faq:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rt("❓ 자주 묻는 질문")}})
        for f in faq[:3]:
            children.append({"object": "block", "type": "toggle",
                             "toggle": {"rich_text": _rt("Q. " + f["q"]),
                                        "children": [{"object": "block", "type": "paragraph",
                                                      "paragraph": {"rich_text": _rt(f["a"])}}]}})
    try:
        page = client.pages.create(
            parent={"database_id": core.NOTION_DATABASE_ID},
            properties={
                "Name": {"title": _rt(item["title_ko"])},
                "URL": {"url": item["url"]},
                "Domain": {"select": {"name": item["domain"]}},
                **({"Category": {"select": {"name": item["category"]}}} if item.get("category") else {}),
                "Tags": {"multi_select": [{"name": t[:50].replace(",", " ")} for t in item.get("tags", [])]},
                **({"Thumbnail": {"files": [{"name": "thumbnail", "type": "external",
                                             "external": {"url": media["image"]}}]}} if media.get("image") else {}),
                **({"Video": {"url": media["video"]}} if media.get("video") else {}),
                "Summary": {"rich_text": _rt(item.get("summary", ""))},
                "Status": {"select": {"name": "Collected"}},
                "CollectedAt": {"date": {"start": item["collected_at"]}},
            },
            children=children,
            **({"cover": {"type": "external", "external": {"url": media["image"]}}} if media.get("image") else {}),
        )
        return page["id"]
    except Exception as e:
        core.log.error("Notion 저장 실패 %s: %s", item["url"], e)
        return None


def backfill_notion(client, limit: int = 100) -> int:
    """카테고리/이미지가 없는 기존 노션 글을 보강 (원문에서 미디어 재수집, LLM 으로 세부 카테고리 분류)."""
    done = 0
    res = _query_db(client, {"page_size": min(limit, 100),
                             "filter": {"property": "Category", "select": {"is_empty": True}}})
    for p in res["results"]:
        pr = p["properties"]
        title = "".join(t["plain_text"] for t in pr["Name"]["title"])
        domain = (pr["Domain"]["select"] or {}).get("name") or "3D DCC"
        summary = "".join(t["plain_text"] for t in pr["Summary"]["rich_text"])
        url = pr["URL"]["url"] or ""
        try:
            cats = core.load_categories()[domain]
            out = core._parse_json(core.llm(
                f"Title: {title}\nSummary: {summary}\nDomain: {domain}\nCategories: {cats}\n"
                'Return JSON {"category": "best existing category, or a new short Korean name (<=10 chars) '
                'only if none fits"}', max_tokens=100, json_mode=True))
            category = core.register_category(domain, out.get("category", ""))
            media = core.fetch_article(url)[1] if url else {}
            props = {"Category": {"select": {"name": category}}}
            if media.get("image"):
                props["Thumbnail"] = {"files": [{"name": "thumbnail", "type": "external",
                                                 "external": {"url": media["image"]}}]}
            if media.get("video"):
                props["Video"] = {"url": media["video"]}
            client.pages.update(page_id=p["id"], properties=props,
                                **({"cover": {"type": "external", "external": {"url": media["image"]}}}
                                   if media.get("image") else {}))
            done += 1
            core.log.info("보강: %s → %s", title[:30], category)
        except Exception as e:
            core.log.warning("보강 실패 %s: %s", title[:30], e)
    return done


def mark_notion_published(client, page_id: str | None, post_url: str) -> None:
    if not (client and page_id):
        return
    try:
        client.pages.update(page_id=page_id, properties={
            "Status": {"select": {"name": "Published"}},
            "TistoryURL": {"url": post_url or None},
        })
    except Exception as e:
        core.log.warning("Notion 상태 업데이트 실패: %s", e)
