# Task 06 — table-of-contents confirmation step (edit only app.py and static/index.html)

graph.py now has (do NOT edit it):
- graph.propose_plan(question, cfg=None) -> {"plan": [{title, role, seed, budget, keywords}], "alarms": [...], "log": [...]}
  (one LLM call, ~30s)
- graph.run(question, cfg=None, label="base", on_log=print, approved_plan=None) — when approved_plan is given,
  the graph skips planning and researches exactly those sections.

## Change the "question" stage
Currently a question in stage "question" starts graph.run immediately. Insert a new stage "toc" between:
1. User asks a question (stage "question") → server runs graph.propose_plan in a background thread (so /chat returns fast:
   reply "목차를 짜는 중입니다…", and push the proposal to the progress SSE/log when ready) — OR, simpler, call it synchronously
   inside /chat (it takes ~30s; the frontend must show a "생각 중…" placeholder while waiting). Pick the synchronous one unless it
   blocks the server; FastAPI runs sync endpoints in a threadpool so it is fine.
2. Reply with the numbered TOC, one line per section: "1. <title> — <role> (시작 문서: <seed or '없음'>)",
   plus any alarms, then: "이대로 조사할까요? '예' / '빼기 2 4' (번호 빼기) / '다시' (목차 다시 짜기)". Stage becomes "toc",
   store question + plan in the session.
3. In stage "toc":
   - '예' (or '네', 'ok') → start graph.run(question, approved_plan=plan, label="demo") via the existing run thread/SSE flow,
     reply "조사를 시작합니다.", return run:true, stage back to "question" after it starts.
   - '빼기 N M …' → remove those sections (1-based), re-show the TOC, stay in "toc". Refuse to remove all.
   - '다시' → propose_plan again, re-show.
   - anything else → repeat the instructions.
- Update the stage label: "1 시장 정하기 · 2 자료 · 3 목차 확인 · 4 조사" (toc = 3, question/run = 4).
- The final report panel should also show which sections the human removed (store removed titles; send in /result as
  "removed_sections").

Check with `python -c "import app"` and a TestClient test with graph.propose_plan and graph.run monkeypatched (no LLM calls):
question → toc shown; '빼기 2' removes; '예' calls run with the reduced plan. Report to @miko.
