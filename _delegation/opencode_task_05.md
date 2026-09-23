# Task 05 — staged chat flow in the web demo (edit only app.py and static/index.html)

Current demo treats any chat input as the research question. Replace with a staged conversation.
Read graph.py, llm.py, collect.py (do NOT edit them). Keep all existing endpoints working.

## Stages (server keeps one in-memory session dict; single user is fine)
1. "scope" — bot greets "어떤 시장을 조사하고 싶으세요?". Each user reply → llm.ask(system, history, coord=True) where
   system asks the bot to narrow the market down (region, segment, period, purpose) with ONE short follow-up question per turn,
   and when it has enough (or after 3 user turns) reply exactly in the form:
   "정리: <한 줄 시장 정의>" . When the reply starts with "정리:", store it as session["scope"] and move to stage 2.
2. "upload" — bot says: "시장조사에 쓸 자료가 있으면 이곳에 끌어다 놓아 주세요. 없으면 '없음'이라고 입력하세요."
   Files dropped → existing /upload/{market} (market = graph.CFG["market"]); after upload, or when user types '없음' / '다음',
   run the readiness check: corpus = graph.load_corpus(graph.CFG["market"]) merged with collect.load_uploads(data/<market>/uploads)
   (uploaded docs get links via collect.build_links on the merged docs only for their own titles) → collect.stats + collect.is_ready.
   - ready → bot: "이용할 준비가 되었습니다 (문서 N건, M자). 어떤 조사를 할까요?" → stage 3
   - not ready → bot: "자료가 부족합니다 (<reason>). 이 자료만으로 분석할까요, 웹에서 더 찾아볼까요? (분석 / 웹검색)".
     '분석' → stage 3 anyway. '웹검색' → bot: "웹 수집은 아직 준비 중입니다. 지금 자료로 진행합니다." → stage 3.
   Do NOT write merged corpus back to disk.
3. "question" — user text → existing run flow (POST /run logic, SSE progress, report panel). After the report, stay in stage 3
   so the user can ask another question.

## API
- POST /chat {"text": "..."} → {"stage": "...", "reply": "..."} ; if stage 3 input, also starts the run and returns
  {"stage":"question","reply":"조사를 시작합니다.","run":true}. Frontend then opens EventSource('/events').
- GET /state → {"stage", "scope"}.
- Show the current stage as a small label above the chat ("1 시장 정하기 · 2 자료 · 3 조사"), highlight the active one.
- In the right "진행 과정" panel, also show readiness stats when checked (문서 수, 글자 수, 링크 중앙값).

Keep textContent-only DOM writes. Check with `python -c "import app"` and a FastAPI TestClient test of /chat stage transitions
with llm.ask monkeypatched to return "정리: 테스트 시장" (no real LLM calls). Report to @miko.
