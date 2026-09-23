"""코퍼스 구축. 형식: {"docs": {제목: 본문}, "links": {제목: [제목]}}"""
import json
import os
import statistics
import sys


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


def is_ready(corpus: dict, min_docs: int = 30, min_chars: int = 400000) -> tuple[bool, str]:
    """수집 충분 여부. 이유 문자열은 한국어."""
    s = stats(corpus)
    if s["doc_count"] < min_docs:
        return False, f"문서 부족: {s['doc_count']}/{min_docs}개"
    if s["total_chars"] < min_chars:
        return False, f"분량 부족: {s['total_chars']}/{min_chars}자"
    return True, f"준비 완료: {s['doc_count']}개 문서, {s['total_chars']}자"


def load_uploads(folder: str) -> dict[str, str]:
    """uploads 폴더에서 .txt/.md만 읽어 {제목: 본문} 반환. 제목=확장자 제외 파일명."""
    # TODO: pdf 지원 추가 (stdlib만 사용 조건과 충돌 시 별도 처리)
    docs: dict[str, str] = {}
    if not os.path.isdir(folder):
        return docs
    for fn in sorted(os.listdir(folder)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in (".txt", ".md"):
            continue
        title = os.path.splitext(fn)[0]
        path = os.path.join(folder, fn)
        try:
            with open(path, encoding="utf-8") as f:
                docs[title] = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="utf-8", errors="ignore") as f:
                docs[title] = f.read()
    return docs


def web_collect(market: str, parts: list[str]) -> dict:
    """웹 수집 스텁. 서브에이전트 기반 수집은 아직 미구현."""
    raise NotImplementedError("web search sub-agents: TODO")


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python collect.py data/<market>/corpus.json")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        corpus = json.load(f)
    s = stats(corpus)
    ok, reason = is_ready(corpus)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(reason)
    print("ready:", ok)


if __name__ == "__main__":
    main()
