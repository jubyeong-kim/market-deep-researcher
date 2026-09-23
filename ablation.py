"""어블레이션. SWITCHES 중 하나씩 끄고 반복 실행해 기능 기여도를 측정.

실행: python ablation.py [--ids 1 2] [--repeats 1]
결과: output/ablation.json {"runs": [...], "summary": {label: {...}}}
"""
import argparse
import copy
import json
import sys
from pathlib import Path

import baseline
import graph

BASE = Path(__file__).parent

SWITCHES = ["assignment", "zones", "redelegation", "links"]

MEAN_KEYS = ["grounding_rate", "concentration", "duplicate_rate", "isolation", "calls", "seconds"]


def _alarms(m: dict) -> int:
    """알람 개수: 인용 실패 + 숫자 불일치 + 점검 알람 + 빈 절."""
    return len(m.get("false_citations", [])) + len(m.get("number_mismatch", [])) \
        + len(m.get("alarms", [])) + len(m.get("empty_sections", []))


def run_ablation(question_ids: list = None, repeats: int = 1) -> dict:
    """질문별·반복별 base/no_*/baseline 실행 후 output/ablation.json 저장."""
    questions = json.load(open(BASE / "data" / "questions.json", encoding="utf-8"))
    if question_ids:
        wanted = set(question_ids)
        questions = [q for q in questions if q["id"] in wanted]
    cfg = graph.CFG
    runs: list[dict] = []
    for q in questions:
        for rep in range(repeats):
            base_read = 0
            jobs = [("base", cfg)]
            jobs += [(f"no_{sw}", None) for sw in SWITCHES]  # cfg는 실행 시점에 deep-copy
            jobs.append(("baseline", "baseline"))
            for label, c in jobs:
                rec = {"label": label, "qid": q["id"], "repeat": rep}
                try:
                    if label == "base":
                        r = graph.run(q["question"], cfg, "base")
                        base_read = len({t for d in r["drafts"].values() for t in d["read"]})
                    elif label.startswith("no_"):
                        cfg2 = copy.deepcopy(cfg)
                        cfg2["switches"][label[3:]] = False
                        r = graph.run(q["question"], cfg2, label)
                    else:
                        r = baseline.run_baseline(q["question"], budget=base_read, label="baseline")
                    m = r["metrics"]
                    rec.update({k: v for k, v in m.items() if k != "citation_list"})
                    rec["dir"] = Path(r["dir"]).name
                except Exception as e:  # 한 번 실패해도 나머지는 계속
                    rec["error"] = f"{type(e).__name__}: {e}"
                runs.append(rec)
    summary: dict[str, dict] = {}
    for label in ["base"] + [f"no_{sw}" for sw in SWITCHES] + ["baseline"]:
        rs = [r for r in runs if r["label"] == label and "error" not in r]
        s = {"n": len(rs), "errors": sum(1 for r in runs if r["label"] == label and "error" in r)}
        for k in MEAN_KEYS:
            vals = [r[k] for r in rs if k in r]
            s[k] = round(sum(vals) / len(vals), 3) if vals else None
        s["alarms"] = sum(_alarms(r) for r in rs)
        summary[label] = s
    out = {"runs": runs, "summary": summary}
    with open(BASE / "output" / "ablation.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    header = f"{'label':<16}{'n':>3}{'ground':>8}{'concen':>8}{'dup':>7}{'isol':>7}{'calls':>7}{'secs':>7}{'alarms':>8}"
    print(header)
    for label, s in summary.items():
        fmt = lambda k: f"{s[k]:>8}" if s[k] is not None else f"{'-':>8}"
        print(f"{label:<16}{s['n']:>3}" + "".join(fmt(k) for k in MEAN_KEYS) + f"{s['alarms']:>8}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", type=int, default=None)
    ap.add_argument("--repeats", type=int, default=1)
    a = ap.parse_args(sys.argv[1:])
    run_ablation(a.ids, a.repeats)
