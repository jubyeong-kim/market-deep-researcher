# Task 07 — compare.py: side-by-side reading sheet for one question (new file only)

Purpose: a human reads reports made with different settings side by side and traces a bad passage to the section and doc.
Do NOT edit other files. stdlib only.

Input: output/runs/<dir>/ folders written by graph.run / baseline.run_baseline. Each has report.md, metrics.json,
visited.json ({section: [docs]}), optionally plan.json ([{title, role, seed, budget, keywords}]) and sections/*.md.
output/runs.jsonl has one JSON line per run with keys incl. "dir", "question", "label".

CLI:
  python compare.py --question-substr "BYD" [--repeat-index 0]
  → picks, for that question, the run of each label (base, no_assignment, no_zones, no_redelegation, no_links, baseline);
    if a label has several runs, take the one at --repeat-index (by time order, default 0).
  → writes output/compare/<first 20 chars of question, safe filename>__r<idx>.md

Sheet layout (markdown):
1. Title = question. A metrics table: rows = labels, cols = 근거율, 편중, 중복률, 격리율, 허위인용 수, 숫자불일치 수, 호출, 초, 멈춘 이유, dir.
2. "목차 비교": for each label, numbered list of section titles with 시작문서 (from plan.json; baseline has none → "(혼자 씀)").
3. "절별 읽은 문서": table rows = label, cols = section → docs read (comma-joined).
4. "읽은 문서 겹침": for each pair (base vs each other label) the set of docs read only by base / only by other / both.
5. "보고서 전문": each label's report.md under a heading, in order. Keep «citations» as they are.
6. At the end, an empty template for the human:
   ## 내 판단 (직접 쓰기)
   - 어느 쪽이 나은가:
   - 이유 (자기 말로):
   - 마음에 안 드는 대목 → 어느 절 → 어느 자료:
Also add a tiny `if __name__` self-check path? No — just make the CLI robust: skip labels with no runs, and print the output path.
Test it on the existing output/runs (use --question-substr "CATL" — runs exist from an earlier experiment in
output/runs_run1.jsonl; accept an optional --runs-file arg defaulting to output/runs.jsonl so the test can point at runs_run1.jsonl).
Report to @miko with the output path.
