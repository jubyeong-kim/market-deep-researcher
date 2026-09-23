"""나란히 읽기 시트: 한 질문의 설정별 보고서를 비교한다.
실행: python compare.py --question-substr "CATL" [--repeat-index 0] [--runs-file output/runs.jsonl]
출력: output/compare/<질문 앞 20자>__r<idx>.md
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent
LABELS = ["base", "no_assignment", "no_zones", "no_redelegation", "no_links", "baseline"]


def load_rows(runs_file: str) -> list:
    rows = []
    with open(runs_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def pick(substr: str, idx: int, rows: list) -> tuple:
    """해당 질문의 라벨별 idx번째 실행 (dir 시간순). 없는 라벨은 건너뜀."""
    match = [r for r in rows if substr in r.get("question", "")]
    if not match:
        print(f"질문 없음: '{substr}' 포함 실행이 {len(rows)}건 중 0건")
        sys.exit(1)
    question = match[0]["question"]
    same_q = [r for r in match if r["question"] == question]
    picked = {}
    for lab in LABELS:
        runs = sorted((r for r in same_q if r.get("label") == lab),
                      key=lambda r: r.get("dir", ""))
        if len(runs) > idx:
            picked[lab] = runs[idx]
        else:
            print(f"건너뜀: {lab} (실행 {len(runs)}건, idx {idx} 없음)")
    if not picked:
        print("고를 실행이 없음")
        sys.exit(1)
    return question, picked


def read_run(d: Path) -> dict:
    """run 폴더에서 지표·보고서·읽은 기록·목차 읽기 (없으면 빈 값)."""
    def load(name, default):
        p = d / name
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    rep = d / "report.md"
    return {
        "metrics": load("metrics.json", {}),
        "report": rep.read_text(encoding="utf-8") if rep.exists() else "(보고서 없음)",
        "visited": load("visited.json", {}),
        "plan": load("plan.json", None),
    }


def cell(v) -> str:
    """표 셀 안전화: 파이프·개행 제거."""
    return str(v).replace("|", "｜").replace("\n", " ")


def f3(v):
    return round(v, 3) if isinstance(v, float) else v


def count(v) -> int:
    return len(v) if isinstance(v, list) else (v if isinstance(v, int) else 0)


def metrics_table(picked: dict, data: dict) -> list:
    cols = ["라벨", "근거율", "편중", "중복률", "격리율", "허위인용 수",
            "숫자불일치 수", "호출", "초", "멈춘 이유", "dir"]
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for lab in LABELS:
        if lab not in picked:
            continue
        m = data[lab]["metrics"] or picked[lab]
        out.append("| " + " | ".join(cell(x) for x in [
            lab, f3(m.get("grounding_rate", "-")), f3(m.get("concentration", "-")),
            f3(m.get("duplicate_rate", "-")), f3(m.get("isolation", "-")),
            count(m.get("false_citations", "-")), count(m.get("number_mismatch", "-")),
            m.get("calls", "-"), m.get("seconds", "-"),
            m.get("stop_reason", "-"), picked[lab].get("dir", "-")]) + " |")
    return out


def toc_compare(picked: dict, data: dict) -> list:
    out = []
    for lab in LABELS:
        if lab not in picked:
            continue
        out.append(f"### {lab}")
        plan = data[lab]["plan"]
        if not plan:
            out.append("- (혼자 씀)")
            continue
        for i, p in enumerate(plan, 1):
            out.append(f"{i}. {p.get('title', '?')} (시작 문서: {p.get('seed') or '없음'})")
    return out


def read_table(picked: dict, data: dict) -> list:
    secs: list[str] = []
    for lab in LABELS:
        if lab not in picked:
            continue
        for s in (data[lab]["visited"] or {}):
            if s not in secs:
                secs.append(s)
    out = ["| 라벨 | " + " | ".join(cell(s) for s in secs) + " |",
           "| --- | " + " | ".join(["---"] * len(secs)) + " |"]
    for lab in LABELS:
        if lab not in picked:
            continue
        vis = data[lab]["visited"] or {}
        out.append("| " + lab + " | "
                   + " | ".join(cell(", ".join(vis.get(s, [])) or "-") for s in secs) + " |")
    return out


def overlap(picked: dict, data: dict) -> list:
    def read_set(lab: str) -> set:
        return {t for docs in (data[lab]["visited"] or {}).values() for t in docs}

    out = []
    base = read_set("base") if "base" in picked else set()
    for lab in LABELS:
        if lab in ("base",) or lab not in picked:
            continue
        other = read_set(lab)
        only_base = sorted(base - other)
        only_other = sorted(other - base)
        both = sorted(base & other)
        out.append(f"### base vs {lab}")
        out.append(f"- base만 읽음 ({len(only_base)}): {', '.join(only_base) or '-'}")
        out.append(f"- {lab}만 읽음 ({len(only_other)}): {', '.join(only_other) or '-'}")
        out.append(f"- 둘 다 읽음 ({len(both)}): {', '.join(both) or '-'}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-substr", required=True)
    ap.add_argument("--repeat-index", type=int, default=0)
    ap.add_argument("--runs-file", default=str(BASE / "output" / "runs.jsonl"))
    a = ap.parse_args()
    rows = load_rows(a.runs_file)
    question, picked = pick(a.question_substr, a.repeat_index, rows)
    data = {lab: read_run(BASE / "output" / "runs" / r["dir"]) for lab, r in picked.items()}

    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", question[:20]).strip("_") or "q"
    out_path = BASE / "output" / "compare" / f"{safe}__r{a.repeat_index}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    L = [f"# {question}", "",
         f"- 라벨: {', '.join(picked)} (repeat-index {a.repeat_index})", "",
         "## 지표 비교", ""]
    L += metrics_table(picked, data) + ["", "## 목차 비교", ""]
    L += toc_compare(picked, data) + ["", "## 절별 읽은 문서", ""]
    L += read_table(picked, data) + ["", "## 읽은 문서 겹침", ""]
    L += overlap(picked, data) + ["", "## 보고서 전문", ""]
    for lab in LABELS:
        if lab in picked:
            L += [f"### {lab}", "", data[lab]["report"], ""]
    L += ["## 내 판단 (직접 쓰기)", "- 어느 쪽이 나은가:", "- 이유 (자기 말로):",
          "- 마음에 안 드는 대목 → 어느 절 → 어느 자료:", ""]
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"labels: {', '.join(picked)}")
    print(str(out_path))


if __name__ == "__main__":
    main()
