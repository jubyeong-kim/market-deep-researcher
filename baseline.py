"""베이스라인(통제집단). 팀과 동일한 읽기 예산 안에서 단일 에이전트가 보고서 통째로 작성.

비교용 기준선: 같은 budget으로 graph.pick_docs가 고른 문서를 읽고
llm.ask 한 번으로 전체 보고서를 쓴다.
실행: python baseline.py "질문"
"""
import json
import sys
import time
from pathlib import Path

import graph
import llm
import metrics

BASE = Path(__file__).parent


def run_baseline(question: str, cfg: dict = None, budget: int = None, label: str = "baseline") -> dict:
    """단일 에이전트로 질문에 답하고 output/runs/<시각>_<라벨>/ 에 저장."""
    cfg = cfg or graph.CFG
    corpus = graph.load_corpus(cfg["market"], cfg["switches"]["uploads"])
    if budget is None:
        budget = cfg["max_sections"] * cfg["section_budget"]  # 팀이 읽을 수 있는 총량과 동일
    for k in llm.USAGE:
        llm.USAGE[k] = 0
    t0 = time.time()
    docs, links = corpus["docs"], corpus["links"]
    # 공정성: 팀 코디네이터와 같은 문서 카드를 보고, 먼저 읽을 문서 + 영어 검색어를 스스로 정한다.
    # (처음엔 한국어 질문으로만 골라 점수가 전부 0 → 코퍼스 앞쪽 24건을 순서대로 읽었다. Q3인데 LG Chem을 못 읽음)
    cards = graph.doc_cards(corpus)
    sel = graph.parse_json(llm.ask(
        f"너는 시장조사 애널리스트다. 질문에 답하려고 문서를 최대 {budget}건 읽을 수 있다. "
        "아래 목록에서 먼저 읽을 문서(제목 그대로)와, 나머지 문서를 찾을 영어 검색어 5~8개를 정하라. "
        'JSON으로만: {"문서":["..."],"검색어":["..."]}',
        f"[질문] {question}\n[문서 카드]\n{cards}", coord=True))
    first = [t for t in dict.fromkeys(sel.get("문서", [])) if t in docs][:budget]   # 지어낸 제목은 코드가 거른다
    read = first + graph.pick_docs({"title": question, "seed": None, "keywords": sel.get("검색어", [])},
                                   docs, links, avoid=set(first), already=[], budget=budget - len(first),
                                   use_links=cfg["switches"]["links"], full=set(corpus.get("uploads", ())))
    material = "\n\n".join(f"### «{t}»\n{docs[t][:graph.DOC_CAP]}" for t in read)
    # 글쓰기 규칙도 팀 조사관과 같게 (인용 위치 규칙이 다르면 근거율 비교가 틀어진다)
    system = ("너는 시장조사 애널리스트다. 아래 자료만으로 질문에 답하는 긴 보고서를 혼자 통째로 써라. "
              "절 구성은 네가 정하고 절 제목은 '## 제목'으로 써라. "
              "아래 자료에 있는 내용만 쓰고, 모든 문장 끝에 근거 문서를 «문서제목» 형식으로 붙여라. 자료에 없는 숫자는 쓰지 마라. "
              "인용은 문장의 마침표 바로 앞에 붙여라 (예: ...생산했다 «LG Chem».). 문장 앞이나 마침표 뒤에 두지 마라. "
              "인사말·'작성하겠습니다' 같은 설명 없이 바로 본문을 써라.")
    if cfg["switches"]["subject_rule"]:   # 팀 조사관과 같은 규칙 (공정성)
        system += " " + graph.SUBJECT_RULE
    report = llm.ask(system, f"[질문] {question}\n[자료]\n{material or '(없음)'}", coord=True)
    budget_used = len(read) / budget if budget else 0.0
    if budget_used < 1.0:
        print(f"WARNING: 예산 미달 {len(read)}/{budget} — 코퍼스가 모자라서 조기 종료 (불공정 비교 주의)")
    m = metrics.compute(report, set(read), docs, len(read),
                        llm.USAGE["coord_chars"], llm.USAGE["sub_chars"])
    m.update(alarms=[], stop_reason="baseline", calls=llm.USAGE["calls"],
             coord_chars=llm.USAGE["coord_chars"], sub_chars=llm.USAGE["sub_chars"],
             empty_sections=(["report"] if graph.n_citations(report) == 0 else []),
             seconds=round(time.time() - t0, 1),
             budget=budget, read=len(read), budget_used=round(budget_used, 3))
    d = BASE / "output" / "runs" / f"{time.strftime('%m%d-%H%M%S')}_{label}"
    d.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (d / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    dump("visited.json", {"baseline": read})
    dump("metrics.json", m)
    (d / "report.md").write_text(report, encoding="utf-8")
    with open(BASE / "output" / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"dir": d.name, "question": question, "label": label,
                            **{k: v for k, v in m.items() if k != "citation_list"}},
                           ensure_ascii=False) + "\n")
    return {"report": report, "read": read, "budget": budget,
            "budget_used": budget_used, "metrics": m, "dir": str(d)}


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "국내외 배터리 3사의 전략 차이는?"
    r = run_baseline(q)
    print(json.dumps({k: v for k, v in r["metrics"].items() if k != "citation_list"},
                     ensure_ascii=False, indent=1))
    print("저장:", r["dir"])
