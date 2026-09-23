# Task 04 — wire the web demo to the real graph (edit only app.py and static/index.html)

Read graph.py (do NOT edit). graph.run(question, cfg=None, label="base", on_log=print) runs the pipeline,
calls on_log(str) for each progress line, and returns dict with keys: report (markdown str), plan (list of
{title, role, seed, budget}), drafts ({section_title: {text, read: [doc titles], insufficient, ...}}),
metrics (dict), dir (output folder). Citations in report look like «문서제목».

## app.py
- Keep GET / and POST /upload/{market}.
- POST /run  JSON {"question": "..."} → start graph.run in a background thread (one run at a time; if busy return 409).
  on_log pushes lines into a queue. Store the final result in memory (drop "corpus" if present).
- GET /events → SSE: stream queued log lines as `data: <line>`; when the run finishes send `event: done` then close.
  Replace the old demo generator.
- GET /result → JSON {question, report, plan, sections: {title: {read, text}}, metrics} of the last finished run.
- GET /doc/{title} → first 1500 chars of that doc from graph.load_corpus(graph.CFG["market"])["docs"] (404 if missing).
- Wrap the thread target in try/except and push "오류: ..." to the log on failure, then send done.

## static/index.html (no frameworks, no CDN, keep it one file)
- Left column "대화": first bot message "어떤 시장을 조사하고 싶으세요?" (placeholder for the scoping step — for now any text
  the user sends is treated as the research question: POST /run, then open EventSource('/events')).
  Keep the drag-and-drop zone.
- Right column "진행 과정": append each SSE line as a list item (newest at bottom). On `done`, fetch /result.
- Below both columns, a "보고서" panel:
  - Render the markdown minimally (## headings, paragraphs). Replace every «X» with a small superscript marker (e.g. "[1]")
    whose title attribute is X (hidden citation that shows on hover); clicking it fetches /doc/X and shows the excerpt in a side box.
  - Under each section heading, a collapsible <details> "이 절을 쓴 조사관이 읽은 문서" listing sections[title].read.
  - A small metrics line: 근거율, 허위 인용 수, 숫자 불일치 수, 격리율, 호출 수, 멈춘 이유.
- Escape all text inserted into the DOM (use textContent / createElement, no innerHTML with raw data).

Check with `python -c "import app"` only. Do not start real runs. Report to @miko.
