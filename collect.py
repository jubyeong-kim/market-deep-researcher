"""코퍼스 구축. 형식: {"docs": {제목: 본문}, "links": {제목: [제목]}}"""
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

WIKI_API = "https://en.wikipedia.org/w/api.php"   # 한국어 위키는 회사 문서가 1~3천 자로 짧아 영어로 바꿈
WIKI_UA = "market-deep-researcher/0.1 (student project)"  # ASCII only


def build_links(docs: dict[str, str]) -> dict[str, list[str]]:
    """A 본문에 B 제목 문자열이 있으면 A->B 링크 (A != B). docs 내부 제목만 유지."""
    titles = set(docs)
    links: dict[str, list[str]] = {}
    for a, text in docs.items():
        out = [b for b in titles if b != a and b in text]
        links[a] = sorted(out)
    return links


def stats(corpus: dict) -> dict:
    """문서 수, 총 글자 수, 문서당 링크 수 중앙값, 링크 0개 제목 목록."""
    docs = corpus.get("docs", {})
    links = corpus.get("links", {})
    counts = [len(links.get(t, [])) for t in docs]
    return {
        "doc_count": len(docs),
        "total_chars": sum(len(v) for v in docs.values()),
        "median_links": statistics.median(counts) if counts else 0,
        "zero_link_titles": sorted([t for t in docs if not links.get(t)]),
    }


def is_ready(corpus: dict, min_docs: int = 30, min_chars: int = 800000) -> tuple[bool, str]:
    """수집 충분 여부. 이유 문자열은 한국어."""
    s = stats(corpus)
    if s["doc_count"] < min_docs:
        return False, f"문서 부족: {s['doc_count']}/{min_docs}개"
    if s["total_chars"] < min_chars:
        return False, f"분량 부족: {s['total_chars']}/{min_chars}자"
    return True, f"준비 완료: {s['doc_count']}개 문서, {s['total_chars']}자"


def load_uploads(folder: str) -> dict[str, str]:
    """uploads 폴더에서 .txt/.md/.pdf를 읽어 {제목: 본문} 반환. 제목=확장자 제외 파일명."""
    docs: dict[str, str] = {}
    if not os.path.isdir(folder):
        return docs
    for fn in sorted(os.listdir(folder)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in (".txt", ".md", ".pdf"):
            continue
        title = os.path.splitext(fn)[0]
        path = os.path.join(folder, fn)
        try:
            if ext == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(path)
                docs[title] = "\n".join((p.extract_text() or "") for p in reader.pages)
            else:
                try:
                    with open(path, encoding="utf-8") as f:
                        docs[title] = f.read()
                except UnicodeDecodeError:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        docs[title] = f.read()
        except Exception as e:
            print(f"경고: {fn} 읽기 실패, 건너뜀 ({e})")
    return docs


def _wiki_api(params: dict, tries: int = 5) -> dict:
    """MediaWiki API 한 번 호출 (호출 사이 0.3초 대기, 429 시 Retry-After 후 재시도)."""
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(WIKI_API + "?" + qs, headers={"User-Agent": WIKI_UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(0.3)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                try:
                    wait = float(e.headers.get("Retry-After", "5"))
                except (TypeError, ValueError):
                    wait = 5.0
                time.sleep(wait + 1)
            else:
                raise


def _fetch_extract(title: str) -> tuple:
    """본문 1건 조회 (제목 1개씩, redirects 해소). (정규제목, 본문, {from: to}) 반환."""
    data = _wiki_api({"action": "query", "prop": "extracts", "explaintext": 1,
                      "titles": title, "redirects": 1, "format": "json"})
    q = data.get("query", {})
    redir = {d["from"]: d["to"] for d in q.get("redirects", [])}
    for page in q.get("pages", {}).values():
        if "missing" in page:
            return None, "", redir
        return page.get("title", title), page.get("extract", "") or "", redir
    return None, "", redir


def _fetch_links(title: str) -> list[str]:
    """문서의 일반문서 링크 전체 (pllimit=max, continue 추적)."""
    out: list[str] = []
    cont: dict = {}
    while True:
        data = _wiki_api({"action": "query", "prop": "links", "titles": title,
                          "plnamespace": 0, "pllimit": "max", "format": "json", **cont})
        for page in data.get("query", {}).get("pages", {}).values():
            out += [lk["title"] for lk in page.get("links", [])]
        if "continue" in data:
            cont = data["continue"]
        else:
            break
    return out


_YEAR_RES = [re.compile(p) for p in
             (r"^\d+년$", r"^\d+년대$", r"^\d+세기$", r"^\d+월 \d+일$",
              r"^\d+년 \d+월( \d+일)?$", r"^\d+월$", r"^\d+일$")]


def _skip_title(t: str) -> bool:
    """연도/날짜, 목록/틀/분류 문서는 제외."""
    if t.startswith(("목록", "틀:", "분류:", "List of", "Template:", "Category:")) or "목록" in t or "(identifier)" in t or re.fullmatch(r"\d{4}", t):
        return True
    return any(p.search(t) for p in _YEAR_RES)


TOPIC = re.compile(r"batter(y|ies)|electric vehicle|EVs?|lithium|cathode", re.I)   # ponytail: 시장이 바뀌면 config로 뺄 것


def _search_title(q: str) -> str:
    """시드 이름을 실제 위키 제목으로 (동음이의·다른 표기 대응): 검색 상위 결과 중 주제어가 든 첫 문서."""
    data = _wiki_api({"action": "query", "list": "search", "srsearch": q + " battery OR electric vehicle",
                      "srlimit": 5, "format": "json"})
    hits = [h["title"] for h in data.get("query", {}).get("search", [])]
    return hits[0] if hits else q


def wiki_collect(seeds: list[str], target_docs: int = 40, min_chars: int = 3000, checkpoint: str = None) -> dict:
    """한국어 위키백과 수집: 시드 우선, 다음은 시드들이 공유한 2홉 후보 순. {"docs","links"} 반환."""
    docs: dict[str, str] = {}
    raw_links: dict[str, list] = {}
    redirect_map: dict[str, str] = {}
    seen: set[str] = set()
    # 중간 저장: 5건마다 checkpoint 에 쓰고, 다시 돌리면 이어서 받는다 (끝에 한 번 저장하면 중단 시 전부 날아감)
    if checkpoint and os.path.exists(checkpoint):
        ck = json.load(open(checkpoint, encoding="utf-8"))
        docs, raw_links, redirect_map = ck["docs"], ck["raw_links"], ck["redirects"]
        seen |= set(docs)
        print(f"이어받기: {len(docs)}건", flush=True)

    def save_ck():
        if checkpoint:
            os.makedirs(os.path.dirname(checkpoint), exist_ok=True)
            json.dump({"docs": docs, "raw_links": raw_links, "redirects": redirect_map},
                      open(checkpoint, "w", encoding="utf-8"), ensure_ascii=False)

    def fetch(req: str):
        canon, text, redir = _fetch_extract(req)
        redirect_map.update(redir)
        # 버릴 짧은 문서는 링크를 안 받는다 (링크 조회가 continue 로 여러 번 호출됨)
        targets = _fetch_links(canon) if canon and len(text) >= min_chars else []
        return canon, text, targets

    def store(req: str, is_seed: bool = False) -> None:
        canon, text, targets = fetch(req)
        if is_seed and (canon is None or len(text) < min_chars):   # 제목이 안 맞으면 검색으로 다시
            canon, text, targets = fetch(_search_title(req))
        if canon is None:
            return None
        if not is_seed and len(TOPIC.findall(text)) < max(5, len(text) / 2000):   # 밀도 기준: 긴 문서가 우연히 통과하지 않게
            seen.add(canon)
            return None
        seen.add(canon)
        redirect_map.setdefault(req, canon)
        if len(text) >= min_chars and canon not in docs:
            docs[canon] = text
            raw_links[canon] = targets
            print(f"[{len(docs)}/{target_docs}] {canon} ({len(text):,}자)", flush=True)
            if len(docs) % 5 == 0:
                save_ck()
        return targets

    cand_counts: Counter = Counter()
    for s in seeds:  # 1) 시드 우선
        if len(docs) >= target_docs:
            break
        if s in seen:
            targets = raw_links.get(redirect_map.get(s, s), [])
        else:
            seen.add(s)
            targets = store(s, is_seed=True)
        for t in targets or []:
            if t not in seen and not _skip_title(t):
                cand_counts[t] += 1
    # 2) 2홉 후보: 여러 시드가 공유한 순
    for cand, _ in sorted(cand_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(docs) >= target_docs:
            break
        if cand in seen or cand in docs or _skip_title(cand):
            continue
        seen.add(cand)
        store(cand)

    def norm(t: str) -> str:  # 리다이렉트 해소
        seen_t: set[str] = set()
        while t in redirect_map and t not in seen_t:
            seen_t.add(t)
            t = redirect_map[t]
        return t

    links = {t: sorted({norm(u) for u in tgts if norm(u) in docs and norm(u) != t})
             for t, tgts in raw_links.items()}
    return {"docs": docs, "links": links}


def web_collect(market: str, parts: list[str]) -> dict:
    """웹 수집 스텁. 서브에이전트 기반 수집은 아직 미구현."""
    raise NotImplementedError("web search sub-agents: TODO")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("사용법: python collect.py data/<market>/corpus.json")
        print("       python collect.py build <market> <seed1> <seed2> ... [--n 5]")
        sys.exit(1)
    if args[0] == "build":
        rest = list(args[1:])
        target_docs = 40
        if "--n" in rest:
            i = rest.index("--n")
            target_docs = int(rest[i + 1])
            del rest[i:i + 2]
        if not rest:
            print("사용법: python collect.py build <market> <seed1> ... [--n 5]")
            sys.exit(1)
        market, seeds = rest[0], rest[1:]
        wiki = wiki_collect(seeds, target_docs=target_docs,
                            checkpoint=os.path.join("data", market, "_checkpoint.json"))
        uploads = load_uploads(os.path.join("data", market, "uploads"))
        docs = dict(wiki["docs"])
        docs.update(uploads)
        links = {t: sorted([u for u in wiki["links"].get(t, []) if u in docs])
                 for t in wiki["docs"]}
        up_links = build_links(docs)  # 업로드는 제목-문자열 링크
        for t in uploads:
            links[t] = up_links[t]
        corpus = {"docs": docs, "links": links}
        path = os.path.join("data", market, "corpus.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(corpus, f, ensure_ascii=False)
    else:
        path = args[0]
        with open(path, encoding="utf-8") as f:
            corpus = json.load(f)
    s = stats(corpus)
    ok, reason = is_ready(corpus)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(reason)
    print("ready:", ok)


if __name__ == "__main__":
    main()
