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
                rec = _one(q, rep, label, base_read)
                if label == "base" and "base_read" in rec:
                    base_read = rec["base_read"]
                runs.append(rec)
    return _save(runs)


def _one(q: dict, rep: int, label: str, base_read: int) -> dict:
    """설정 하나로 한 번 실행해 기록 한 줄을 만든다. 실패해도 예외 대신 error 를 남긴다."""
    cfg = graph.CFG
    rec = {"label": label, "qid": q["id"], "repeat": rep}
    try:
        if label == "base":
            r = graph.run(q["question"], cfg, "base")
            rec["base_read"] = len({t for d in r["drafts"].values() for t in d["read"]})
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
    return rec


def retry_errors() -> dict:
    """output/ablation.json 에서 error 난 실행만 다시 돌려 그 자리에 바꿔 넣는다 (사용량 한도로 끊긴 경우용)."""
    questions = {q["id"]: q for q in json.load(open(BASE / "data" / "questions.json", encoding="utf-8"))}
    runs = json.load(open(BASE / "output" / "ablation.json", encoding="utf-8"))["runs"]
    for i, r in enumerate(runs):
        if "error" not in r:
            continue
        # 대조군 예산 = 같은 질문·같은 반복의 base 가 읽은 문서 수 (base 도 실패했으면 앞에서 다시 돌린 값)
        base = next((x for x in runs if x["qid"] == r["qid"] and x["repeat"] == r["repeat"]
                     and x["label"] == "base" and "error" not in x), {})
        print(f"재시도: Q{r['qid']} {r['label']} 반복{r['repeat']}", flush=True)
        runs[i] = _one(questions[r["qid"]], r["repeat"], r["label"], base.get("base_read", 0))
    return _save(runs)


def _save(runs: list) -> dict:
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
    ap.add_argument("--retry-errors", action="store_true", help="ablation.json 의 실패한 실행만 다시")
    a = ap.parse_args(sys.argv[1:])
    retry_errors() if a.retry_errors else run_ablation(a.ids, a.repeats)
