# Task 09 — lazy (chunked) pre-filter for the collector (edit only collect.py)

Your task 08 finding was right: filtering all 1534 candidates up front costs more calls than it saves at small n.
Make the pre-filter lazy:
- Walk the ranked 2-hop candidates in chunks of 20 (skip already-seen / _skip_title first).
- For each chunk: one prop=info length call (whole chunk) → drop length < min_chars; then (if intro_filter) one exintro call
  for the survivors → drop zero TOPIC matches; then full-fetch survivors one by one with the existing filters.
- Stop as soon as target_docs is reached (do not pre-filter later chunks).
- Keep the stats line, the --no-intro-filter flag, checkpoints, 429 handling, everything else as is.

Test (throwaway market only, never data/ev-battery/):
- `--n 12` with the same seeds as before → must be <= the old path's calls (42) or close, same kept titles.
- `--n 25` with the same seeds, new lazy path vs old path copy (run them one after another, NOT at the same time, so 429s
  from one run don't slow the other). Report calls, seconds, kept titles for both.
Delete the throwaway folders. Report to @miko.
