# Task 08 — make the Wikipedia collector faster (edit only collect.py)

Problem: `python collect.py build ev-battery ... --n 45` took ~40 minutes. Most time goes to 2-hop candidates that are
fetched in full (extracts + links) and then thrown away by the length filter (< min_chars) or the topic-density filter
(TOPIC regex, `len(TOPIC.findall(text)) < max(5, len(text)/2000)`). Extracts are one title per call + 0.3s sleep.

## Do
1. Batch pre-filter candidates BEFORE fetching full text, in the 2-hop loop:
   - Length: `action=query&prop=info&titles=A|B|...` (up to 50 titles per call, follow `redirects=1`). Page `length` is
     wikitext bytes, always >= plain-text length, so `length < min_chars` can be skipped safely.
   - Topic: `prop=extracts&exintro=1&explaintext=1&exlimit=20&titles=...` (intro only, up to 20 titles per call).
     Skip candidates whose intro has zero TOPIC matches. Put this behind a parameter `intro_filter=True` so it can be turned off.
   - Only survivors go through the existing full fetch + existing filters (keep those filters unchanged).
2. Keep everything else identical: seed handling (incl. _search_title fallback), checkpoint save/resume, redirect
   normalization, output format, CLI. Keep 0.3s sleep between API calls and the 429 Retry-After handling.
3. Print a final line: "API 호출 N회, 걸린 시간 M초, 후보 K개 중 사전필터 탈락 J개".

## Test — IMPORTANT
- NEVER write to data/ev-battery/ (an experiment is reading that corpus right now).
- Use a throwaway market name, e.g. `python collect.py build speedtest "Electric vehicle" "Lithium-ion battery" "CATL" --n 12`
  once with the new code and once with `intro_filter` off (add a CLI flag `--no-intro-filter`), and compare API calls and
  seconds. If feasible also time the old code path on the same seeds (git stash or a copy of the old function) for a fair
  before/after number. Check that the kept documents are on-topic (list titles).
- Delete data/speedtest/ afterwards.
Report to @miko with the before/after numbers and the kept titles.
