"""지표 규칙을 고친 뒤 기존 실행을 같은 규칙으로 다시 채점한다 (보고서는 그대로, 채점만 새로).
python rescore.py [실행 폴더] → output/ablation_rescored.json + 질문별 표
  실행 폴더 기본값 output/runs (worktree 에서는 원래 폴더의 output/runs 를 넘긴다 — 읽기만 한다)
  원래 = ablation.json (실행 당시 규칙) · 직전 = 지난번 ablation_rescored.json · 지금 = 현재 metrics.py"""
import json
import statistics as st
import sys
from pathlib import Path

import metrics

BASE = Path(__file__).parent
RUNS = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "output/runs"
OUT = BASE / "output/ablation_rescored.json"
docs = json.load(open(BASE / "data/ev-battery/corpus.json", encoding="utf-8"))["docs"]
runs = json.load(open(BASE / "output/ablation.json", encoding="utf-8"))["runs"]
prev = {r["dir"]: r for r in json.load(open(OUT, encoding="utf-8"))["runs"] if "dir" in r} if OUT.exists() else {}
changed = 0
for r in runs:
    if r.get("error"):
        continue
    rep = (RUNS / r["dir"] / "report.md").read_text(encoding="utf-8")
    r["grounding_rate_old"], r["sentence_count_old"] = r["grounding_rate"], r["sentence_count"]
    r["grounding_rate_prev"] = prev.get(r["dir"], r)["grounding_rate"]
    r["grounding_rate"] = metrics.grounding_rate(rep)
    r["sentence_count"] = len(metrics.sentences(rep))
    r["number_mismatch"] = metrics.number_mismatch(rep, docs)
    changed += abs(r["grounding_rate"] - r["grounding_rate_prev"]) > 1e-9
json.dump({"note": "제목 줄 제외 · 약어 마침표 처리 · 표는 칸 단위 후 재채점", "runs": runs},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

ok = [r for r in runs if not r.get("error")]
print(f"직전 규칙 대비 근거율이 바뀐 실행: {changed}/{len(ok)}")
for q in sorted({r["qid"] for r in ok}):
    print(f"Q{q}")
    for label in ["base", "no_assignment", "no_zones", "no_redelegation", "no_links", "baseline"]:
        R = [r for r in ok if r["qid"] == q and r["label"] == label]
        mean = lambda k: st.mean(r[k] for r in R)
        print(f"  {label:16} 근거율 원래 {mean('grounding_rate_old'):.2f} → 직전 {mean('grounding_rate_prev'):.2f}"
              f" → 지금 {mean('grounding_rate'):.2f}   문장 {mean('sentence_count'):.0f}"
              f"   숫자불일치 {st.mean(len(r['number_mismatch']) for r in R):.1f}")
