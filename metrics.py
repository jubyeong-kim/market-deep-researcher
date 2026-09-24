"""인용 기반 지표. 정답지 없이 보고서 텍스트만으로 계산. LLM 불필요."""
import re
from collections import Counter

CIT_RE = re.compile(r"«([^»]+)»")
NUM_RE = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?%?")
# 문장 분리: ? ! 。 개행은 항상, 마침표는 숫자 사이 소수점(3.2)이 아닐 때만
SENT_SPLIT_RE = re.compile(r"[?!。\n]+|(?<!\d)\.|\.(?!\d)")
TABLE_SEP_RE = re.compile(r"^\|[\s:|-]*-[\s:|-]*$")        # |---|---|
NO_DATA_RE = re.compile(r"^\(?(자료|카드) 없음\)?\.?$")


def _lines(text: str):
    """제목 줄(#)은 빼고, 표 행은 칸마다 한 줄로 편다.
    비교표 칸 하나 = 조사관 카드 한 줄 = 주장 하나. 행째 한 문장으로 세면 머리 행·구분선이 '근거 없는 문장'이 되고
    칸이 마침표마다 제멋대로 잘린다 (가짜 표로 재 보니 인용 3/3인 표가 근거율 0.43).
    빼는 것: 머리 행(열 이름 = 절 제목) · 구분선 · 첫 칸(축 이름) · '자료 없음'/'(카드 없음)' 칸 (주장이 아니라 빈칸 표시)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#") or TABLE_SEP_RE.match(s):
            continue
        if s.startswith("|"):
            if i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1].strip()):
                continue
            yield from (c for c in s.strip("|").split("|")[1:] if not NO_DATA_RE.match(c.strip()))
            continue
        yield line


def citations(text: str) -> list[str]:
    """모든 «...» 제목을 순서대로 반환."""
    return [m.group(1).strip() for m in CIT_RE.finditer(text)]


def sentences(text: str) -> list[str]:
    """문장 분리: . ? ! 。 개행 기준, 빈 문자열 제거.
    마침표 뒤에 붙은 인용은 앞 문장 것으로 본다 — 안 그러면 다음 문장에 붙어 근거율이 틀린다."""
    text = re.sub(r"([.?!。])[ \t]*((?:«[^»]+»[ \t]*)+)", r" \2\1 ", text)
    # 제목 줄(#)은 문장이 아니다 — 세면 절이 많은 쪽(팀)이 체계적으로 불리해진다 (Q3 읽다가 발견). 표는 칸 단위로
    text = "\n".join(_lines(text))
    # 약어의 마침표에서 자르지 않는다 ("Solutions Inc." 에서 잘려 인용이 다음 조각으로 넘어감)
    text = re.sub(r"\b(Inc|Co|Ltd|Corp|U\.S|St|No|vs)\.", lambda m: m.group(1).replace(".", "") + "", text)
    return [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()]


def grounding_rate(text: str) -> float:
    """인용이 1개 이상인 문장 비율."""
    sents = sentences(text)
    if not sents:
        return 0.0
    hit = sum(1 for s in sents if CIT_RE.search(s))
    return hit / len(sents)


def false_citations(text: str, visited: set) -> set:
    """인용됐지만 읽은 적 없는 문서 (ALARM, 0이어야 함)."""
    return set(citations(text)) - set(visited)


def concentration(text: str) -> float:
    """최다 인용 문서의 전체 인용 중 비중 (없으면 0)."""
    cits = citations(text)
    if not cits:
        return 0.0
    top = Counter(cits).most_common(1)[0][1]
    return top / len(cits)


def duplicate_rate(read_attempts: int, unique_read: int) -> float:
    """1 - unique/attempts (attempts==0이면 0)."""
    if read_attempts == 0:
        return 0.0
    return 1.0 - unique_read / read_attempts


def number_mismatch(text: str, docs: dict[str, str]) -> list[tuple[str, str]]:
    """각 문장의 숫자 토큰이 그 문장에서 인용한 문서 텍스트에 없으면 (문장, 숫자) 반환. (ALARM)"""
    bad: list[tuple[str, str]] = []
    for sent in sentences(text):
        cited = [m.group(1).strip() for m in CIT_RE.finditer(sent)]
        # 날짜·서수(2021년 10월 1일, 3번째, 3사)는 영어 원문과 표기가 달라 비교가 안 되므로 뺀다
        for num in [m.group(0) for m in NUM_RE.finditer(sent)
                    if not re.match(r"\s*(년|월|일|번째|위|사|개국|분기)", sent[m.end():])]:
            if not cited:
                bad.append((sent, num))
                continue
            if not any(num in docs.get(t, "") for t in cited):
                bad.append((sent, num))
    return bad


def compute(report: str, visited: set, docs: dict[str, str],
            read_attempts: int, coord_chars: int, sub_chars: int) -> dict:
    """전체 지표 딕셔너리."""
    total = coord_chars + sub_chars
    return {
        "citation_list": citations(report),
        "citation_count": len(citations(report)),
        "sentence_count": len(sentences(report)),
        "grounding_rate": grounding_rate(report),
        "false_citations": sorted(false_citations(report, visited)),
        "concentration": concentration(report),
        "duplicate_rate": duplicate_rate(read_attempts, len(visited)),
        "number_mismatch": number_mismatch(report, docs),
        "isolation": coord_chars / total if total else 0.0,
    }


if __name__ == "__main__":
    # citations: 순서대로 추출
    assert citations("a«A»b«B»c«A»") == ["A", "B", "A"]
    assert citations("인용 없음") == []
    # sentences: 구분자 분리, 빈 문자열 제거
    assert sentences("첫째. 둘째? 셋째! 넷째。다섯째\n여섯째") == ["첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째"]
    assert sentences("") == []
    # 표: 칸 하나 = 문장 하나. 머리 행·구분선·축 이름·빈칸 표시는 세지 않는다
    t = "| 축 | A | B |\n|---|---|---|\n| 위치 | 2위 «X». | 자료 없음 |\n| 기술 | (카드 없음) | 전고체 «Y» |"
    assert sentences(t) == ["2위 «X»", "전고체 «Y»"] and grounding_rate(t) == 1.0
    # grounding_rate: 인용 문장 비율
    assert grounding_rate("인용 있음«A». 인용 없음.") == 0.5
    assert grounding_rate("") == 0.0
    # false_citations: 읽지 않은 인용
    assert false_citations("«A»«B»", {"A"}) == {"B"}
    assert false_citations("«A»", {"A"}) == set()
    # concentration: 최다 인용 비중
    assert concentration("«A»«A»«B»") == 2 / 3
    assert concentration("인용 없음") == 0.0
    # duplicate_rate
    assert duplicate_rate(0, 0) == 0.0
    assert abs(duplicate_rate(10, 7) - 0.3) < 1e-9
    # number_mismatch: 인용 문서에 숫자가 있어야 통과
    docs = {"A": "매출 15% 증가", "B": "관련 없음"}
    assert number_mismatch("매출 15% 증가«A».", docs) == []
    bad = number_mismatch("매출 3.2% 증가«B».", docs)
    assert len(bad) == 1 and bad[0][1] == "3.2%"
    bad2 = number_mismatch("수치 99가 있다.", docs)  # 인용 없이 숫자
    assert len(bad2) == 1
    # compute
    r = compute("매출 15% 증가«A».", {"A"}, docs, 5, 100, 300)
    assert r["grounding_rate"] == 1.0 and r["isolation"] == 0.25
    assert r["false_citations"] == [] and r["number_mismatch"] == []
    print("metrics.py demo OK")
