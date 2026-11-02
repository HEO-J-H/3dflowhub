"""사이트 자체 검색기 (RAG 의 '찾기' 단계) — 외부 서비스·추가 설치 없이 BM25 로 우리 콘텐츠에서 관련 자료를 찾는다.

쓰임:
 1) AI 가 가이드·오류 해결을 쓸 때 사이트에 이미 있는 관련 글을 근거로 붙여 줌 (일관성·내부 링크)
 2) 사이트의 '관련 글' 을 같은 분류가 아니라 내용이 가까운 글로 (내부 링크 구조)
한국어·영어 섞인 글을 위해: 영어는 단어, 한국어는 2글자 조각(bigram)으로 나눠 색인 — 형태소 분석기 없이도 잘 맞음.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_WORD = re.compile(r"[a-z0-9]+(?:[.\-+][a-z0-9]+)*|[가-힣]+")
STOP = {"the", "and", "for", "with", "a", "an", "of", "to", "in", "on", "is", "how", "new", "3d", "및", "기능", "방법"}


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall((text or "").lower()):
        if w in STOP:
            continue
        if "가" <= w[0] <= "힣":
            out += [w] if len(w) <= 2 else [w[i:i + 2] for i in range(len(w) - 1)]
        elif len(w) > 1:
            out.append(w)
    return out


class Index:
    """BM25 색인. docs = [{'id', 'kind', 'title', 'text', 'url', ...}]"""

    def __init__(self, docs: list[dict], k1: float = 1.4, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = [Counter(tokens(f"{d.get('title', '')} {d.get('title', '')} {d.get('text', '')}")) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1
        df = defaultdict(int)
        for t in self.tf:
            for w in t:
                df[w] += 1
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: str, k: int = 5, kinds: tuple[str, ...] | None = None, exclude: set[str] | None = None,
               min_score: float = 1.0) -> list[dict]:
        q = Counter(tokens(query))
        scored = []
        for i, d in enumerate(self.docs):
            if (kinds and d.get("kind") not in kinds) or (exclude and d.get("id") in exclude):
                continue
            tf, dl, s = self.tf[i], self.len[i], 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            if s >= min_score:
                scored.append((s, i))
        return [{**self.docs[i], "score": round(s, 2)} for s, i in sorted(scored, reverse=True)[:k]]


def site_docs() -> list[dict]:
    """사이트 콘텐츠 → 검색 문서 (글·기초 가이드·오류 해결·바뀐 점)."""
    import build_site
    import guides
    import refs
    docs = []
    for p in build_site.load_posts():
        body = " ".join(f"{s.get('heading', '')} {s.get('body', '')}" for s in p.get("sections") or [] if isinstance(s, dict))
        docs.append({"id": p["id"], "kind": "post", "title": p.get("title_ko", ""), "url": f"p/{p['id']}.html",
                     "text": f"{p.get('summary', '')} {p.get('category', '')} {body[:1500]}", "tool": p.get("category", "")})
    import core
    gstate = core.curation_state()  # 현황판에서 숨긴 가이드는 사이트에 없으므로 제외 (깨진 링크 방지)
    for g in (g for g in guides.load_all() if gstate.get("learn:" + g["id"]) != "hide"):
        docs.append({"id": g["id"], "kind": "guide", "title": f"{g.get('tool', '')} {g['title']}", "url": build_site.learn_url(g),
                     "text": f"{g.get('name', '')} {g.get('summary', '')} {' '.join(g.get('steps', []))}", "tool": g.get("tool", "")})
    for x in refs.load("fix"):
        docs.append({"id": x["id"], "kind": "fix", "title": x["title"], "url": f"fix/{x['id']}/",
                     "text": f"{x.get('error', '')} {x.get('summary', '')} {' '.join(x.get('causes', []))}", "tool": x.get("tool", "")})
    for x in refs.load("change"):
        docs.append({"id": x["id"], "kind": "change", "title": x["title"], "url": f"changes/{x['id']}/",
                     "text": x.get("summary", "") + " " + " ".join(h.get("change", "") for h in x.get("highlights", [])),
                     "tool": x.get("tool", "")})
    import compare
    for x in compare.load_all():
        docs.append({"id": x["id"], "kind": "compare", "title": f"{x['title']} 툴별 비교", "url": f"compare/{x['id']}/",
                     "text": x.get("summary", "") + " " + " ".join(f"{r.get('tool', '')} {r.get('where', '')}" for r in x["rows"]),
                     "tool": ""})
    return docs


_INDEX: Index | None = None


def index(refresh: bool = False) -> Index:
    global _INDEX
    if _INDEX is None or refresh:
        _INDEX = Index(site_docs())
    return _INDEX


def context_for(query: str, k: int = 4, exclude: set[str] | None = None, kinds: tuple[str, ...] | None = None) -> str:
    """AI 글쓰기에 붙일 근거 — 사이트에 이미 있는 관련 자료 요약 (없으면 빈 문자열)."""
    hits = index().search(query, k=k, exclude=exclude, kinds=kinds, min_score=2.0)
    if not hits:
        return ""
    return "Related pages already on this site (stay consistent with them; do not contradict):\n" + "\n".join(
        f"- [{h['kind']}] {h['title']}: {h['text'][:220]}" for h in hits)
