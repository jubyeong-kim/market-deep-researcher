# Task 03 — baseline.py and ablation.py (edit only these two files)

Read graph.py first (do NOT edit it). Reuse: graph.load_corpus, graph.pick_docs, graph.DOC_CAP, graph.CFG, graph.run, llm.ask, llm.USAGE, metrics.compute.

## baseline.py — single-agent control group, SAME reading budget
run_baseline(question, cfg=None, budget=None, label="baseline") -> dict
- budget default = cfg["max_sections"] * cfg["section_budget"]  (same total docs the team may read). Allow override so ablation can pass the team's actual read count.
- Pick docs with graph.pick_docs(sec={"title": question, "seed": None}, docs, links, avoid=set(), already=[], budget=budget, use_links=cfg["switches"]["links"]).
- ONE llm.ask(system, user, coord=True) call: system prompt = market-research analyst writes the whole long report with sections chosen by itself, every sentence ends with «문서제목», no numbers not in the material. user = question + material ("### «title»\n" + text[:graph.DOC_CAP] per doc).
- Record budget, docs actually read, and budget_used = read/budget (must be 1.0 unless corpus ran out — print a WARNING otherwise; a control group that stops early is not a fair fight).
- metrics.compute(report, set(read), docs, len(read), llm.USAGE["coord_chars"], llm.USAGE["sub_chars"]) — reset llm.USAGE first.
- Save like graph.run does: output/runs/<%m%d-%H%M%S>_<label>/ with report.md, visited.json, metrics.json; append a line to output/runs.jsonl (same keys style as graph.run, drop citation_list).
- CLI: python baseline.py "question"

## ablation.py
SWITCHES = ["assignment", "zones", "redelegation", "links"]
run_ablation(question_ids=None, repeats=1) -> dict
- Load data/questions.json (list of {id, question, why_split, type}); filter by ids if given.
- For each question, each repeat: graph.run(q, cfg, "base"); for each switch: deep-copied cfg with that switch False → graph.run(q, cfg2, f"no_{sw}"); then baseline.run_baseline(q, budget=<docs read in the base run>, label="baseline").
- Collect per-run metrics; aggregate per label: mean of grounding_rate, concentration, duplicate_rate, isolation, calls, seconds, and counts of alarms (len false_citations + len number_mismatch + len alarms + len empty_sections).
- Save output/ablation.json {"runs": [...], "summary": {label: {...}}}; print a small table.
- CLI: python ablation.py [--ids 1 2] [--repeats 1]
- Wrap each run in try/except: log the error into the run record and continue.

Check only with `python -c "import baseline, ablation"` (the corpus may not exist yet; do NOT run real LLM calls). Report to @miko.
