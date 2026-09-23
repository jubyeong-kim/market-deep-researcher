# Task for OpenCode — project skeleton files (market-research deep researcher)

Working dir: this folder. Python 3.14, Windows. Use only stdlib + fastapi + uvicorn (already installed). NO other packages.
Another agent (Claude) is writing graph.py, llm.py, config.json at the same time. DO NOT create or edit those three files.
Keep code short. Korean comments/docstrings are fine. Write these files only:

1. metrics.py — citation-based metrics, no answer key, no LLM.
   Citations look like «문서제목» inside text.
   - citations(text) -> list[str]            # all «...» titles, in order
   - sentences(text) -> list[str]           # split on . ? ! 。 and newlines, drop empty
   - grounding_rate(text) -> float          # share of sentences with >=1 citation
   - false_citations(text, visited:set) -> set   # cited but never read  (ALARM, must be 0)
   - concentration(text) -> float           # top cited doc share of all citations (0 if none)
   - duplicate_rate(read_attempts:int, unique_read:int) -> float   # 1 - unique/attempts (0 if attempts==0)
   - number_mismatch(text, docs:dict[str,str]) -> list[tuple[str,str]]
       for each sentence, every number token (e.g. 3.2, 15%, 1,200) must appear in the text of at least one doc cited in that sentence; return (sentence, number) pairs that fail. (ALARM)
   - compute(report, visited:set, docs:dict, read_attempts:int, coord_chars:int, sub_chars:int) -> dict with all of the above plus isolation = coord_chars/(coord_chars+sub_chars)
   - `if __name__ == "__main__":` a small demo with assert checks for each function.

2. collect.py — corpus building. Corpus format: {"docs": {title: text}, "links": {title: [titles]}}
   - build_links(docs) -> dict: A links to B if B's title string appears in A's text (A != B). Keep only titles in docs.
   - stats(corpus) -> dict: doc count, total chars, median links per doc, list of titles with 0 links
   - is_ready(corpus, min_docs=30, min_chars=400000) -> tuple[bool, str]  (reason string in Korean)
   - load_uploads(folder) -> dict[title, text]  for .txt/.md only for now (TODO comment for pdf)
   - web_collect(market, parts) -> dict   # stub: raise NotImplementedError("web search sub-agents: TODO")
   - main: `python collect.py data/<market>/corpus.json` prints stats + is_ready.

3. baseline.py — stub. Single-agent control group with the SAME reading budget as the team. One function run_baseline(question, cfg, corpus) raising NotImplementedError, plus a docstring explaining it.

4. ablation.py — stub. SWITCHES = ["assignment", "zones", "redelegation", "links"]. run_ablation(questions, cfg, corpus, repeats=3) raising NotImplementedError, docstring: turns one switch off at a time, saves output/ablation.json.

5. app.py — FastAPI.
   - GET / -> static/index.html
   - POST /upload/{market} (multipart, multiple files) -> save to data/{market}/uploads/, return saved filenames. Sanitize filenames (basename only).
   - GET /events -> Server-Sent Events stream; for now emit 5 demo events ("기획", "배치", "조사", "점검", "종합") one per second then close.
   - run with: uvicorn app:app --reload
   (python-multipart may be missing: if so, write the upload endpoint anyway and note it in requirements.txt)

6. static/index.html — single file, no frameworks, no CDN. Two columns: left = chat (message list + input box), right = "진행 과정" panel. A drag-and-drop zone ("자료를 여기에 끌어다 놓으세요") that POSTs to /upload/demo. A button that opens EventSource('/events') and appends each event to the right panel. Plain CSS, readable, works on narrow screens.

7. requirements.txt — langgraph, claude-agent-sdk, fastapi, uvicorn, python-multipart, openai

8. .gitignore — .env, __pycache__/, output/, data/*/uploads/, .venv/

9. data/questions.json — template list with 2 example items: {"id":1, "question":"...", "why_split":"...", "type":"single|scattered|follow"}

When done, run `python metrics.py` and `python -c "import app, collect, baseline, ablation"` to check, then reply via hcom to the sender with a short list of files written and check results.
