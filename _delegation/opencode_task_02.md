# Task 02 — Wikipedia corpus collector + PDF uploads (edit collect.py only, plus requirements.txt)

Keep existing functions (build_links, stats, is_ready, load_uploads, main). Do NOT touch other files.
You may `pip install pypdf` (pure python).

1. wiki_collect(seeds: list[str], target_docs=40, min_chars=3000) -> dict   # returns {"docs":..., "links":...}
   - Korean Wikipedia MediaWiki API https://ko.wikipedia.org/w/api.php (no HTML scraping). Use urllib (stdlib) only.
   - User-Agent header ASCII only, e.g. "market-deep-researcher/0.1 (student project)".
   - Body text: action=query&prop=extracts&explaintext=1&titles=<one title>&redirects=1  (ONE title per call). Sleep 0.3s between calls.
   - Links: prop=links&plnamespace=0&pllimit=max, follow `continue` until done.
   - Seeds first. Then 2nd-hop candidates = link targets of seeds, ranked by how many seeds point to them (most shared first).
   - Skip titles that are years/dates (e.g. "2023년", "3월 1일"), or start with "목록", "틀:", "분류:", or contain "목록".
   - Skip docs whose text < min_chars. Stop at target_docs.
   - Store links only between titles that are in docs (the real wiki link graph, not build_links). Resolve redirects so titles match.
   - Print progress: "[12/40] 현대자동차 (18,203자)".
2. load_uploads: also read .pdf via pypdf (join page texts). Skip files that fail with a printed warning.
3. CLI:
   - `python collect.py build <market> <seed1> <seed2> ...` → wiki_collect, merge load_uploads(data/<market>/uploads) into docs (uploads get links from build_links), save data/<market>/corpus.json (utf-8, ensure_ascii=False), then print stats + is_ready.
   - `python collect.py data/<market>/corpus.json` → stats + is_ready (existing behavior).
4. Add pypdf to requirements.txt.

Test with: `python collect.py build test 전기자동차 테슬라` but pass target_docs=5 via an optional `--n 5` flag, then delete data/test/. Report to @miko with the printed stats.
