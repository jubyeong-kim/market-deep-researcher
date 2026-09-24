"""지표 규칙을 고친 뒤 기존 실행을 같은 규칙으로 다시 채점한다 (보고서는 그대로, 채점만 새로).
python rescore.py → output/ablation_rescored.json + 질문별 표"""
import json
import statistics as st
from pathlib import Path

import metrics

BASE = Path(__file__).parent
docs = json.load(open(BASE / "data/ev-battery/corpus.json", encoding="utf-8"))["docs"]
runs = json.load(open(BASE / "output/ablation.json", encoding="utf-8"))["runs"]
for r in runs:
    if r.get("error"):
        continue
    d = BASE / "output/runs" / r["dir"]
    rep = (d / "report.md").read_text(encoding="utf-8")
    r["grounding_rate_old"], r["sentence_count_old"] = r["grounding_rate"], r["sentence_count"]
    r["grounding_rate"] = metrics.grounding_rate(rep)
    r["sentence_count"] = len(metrics.sentences(rep))
    r["number_mismatch"] = metrics.number_mismatch(rep, docs)
json.dump({"note": "제목 줄 제외 · 약어 마침표 처리 후 재채점", "runs": runs},
          open(BASE / "output/ablation_rescored.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

ok = [r for r in runs if not r.get("error")]
for q in sorted({r["qid"] for r in ok}):
    print(f"Q{q}")
    for label in ["base", "no_assignment", "no_zones", "no_redelegation", "no_links", "baseline"]:
        R = [r for r in ok if r["qid"] == q and r["label"] == label]
        old, new = st.mean(r["grounding_rate_old"] for r in R), st.mean(r["grounding_rate"] for r in R)
        print(f"  {label:16} 근거율 {old:.2f} → {new:.2f}   문장 {st.mean(r['sentence_count'] for r in R):.0f}"
              f"   숫자불일치 {st.mean(len(r['number_mismatch']) for r in R):.1f}")
