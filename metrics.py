"""인용 기반 지표. 정답지 없이 보고서 텍스트만으로 계산. LLM 불필요."""
import re
from collections import Counter

CIT_RE = re.compile(r"«([^»]+)»")
NUM_RE = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?%?")
# 문장 분리: ? ! 。 개행은 항상, 마침표는 숫자 사이 소수점(3.2)이 아닐 때만
SENT_SPLIT_RE = re.compile(r"[?!。\n]+|(?<!\d)\.|\.(?!\d)")


def citations(text: str) -> list[str]:
    """모든 «...» 제목을 순서대로 반환."""
    return [m.group(1).strip() for m in CIT_RE.finditer(text)]


def sentences(text: str) -> list[str]:
    """문장 분리: . ? ! 。 개행 기준, 빈 문자열 제거."""
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
        for num in NUM_RE.findall(sent):
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
