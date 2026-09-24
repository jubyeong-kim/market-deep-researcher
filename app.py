"""FastAPI 앱. 실행: uvicorn app:app --reload"""
import os
import queue
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

import collect
import graph
import llm

BASE = Path(__file__).parent
app = FastAPI()

_state = {"running": False, "done": False, "queue": None, "result": None,
           "question": "", "removed": []}
_lock = threading.Lock()

# 단계별 대화 세션 (1인용, 인메모리): scope → upload → question → toc(목차 확인)
_session = {"stage": "scope", "scope": "", "turns": 0, "history": [], "pending_choice": False,
            "pending_q": "", "pending_plan": [], "pending_axes": [], "removed": []}


def _push(line: str) -> None:
    q = _state["queue"]
    if q is not None:
        q.put(str(line).replace("\r", "").replace("\n", " "))


def _run_target(question: str, approved_plan=None, label: str = "base", axes=None) -> None:
    try:
        res = graph.run(question, label=label, on_log=_push, approved_plan=approved_plan, approved_axes=axes)
        with _lock:
            _state["result"] = {k: v for k, v in res.items() if k != "corpus"}
    except Exception as e:
        _push(f"오류: {type(e).__name__}: {e}")
    finally:
        with _lock:
            _state["running"] = False
            _state["done"] = True


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/upload/{market}")
async def upload(market: str, files: list[UploadFile]):
    """multipart 다중 파일 업로드를 data/{market}/uploads/에 저장."""
    dest = os.path.join(BASE, "data", os.path.basename(market), "uploads")
    os.makedirs(dest, exist_ok=True)
    saved = []
    for f in files:
        name = os.path.basename(f.filename or "unnamed")  # 경로 제거 (살균)
        if not name:
            continue
        path = os.path.join(dest, name)
        with open(path, "wb") as out:
            out.write(await f.read())
        saved.append(name)
    return {"saved": saved}


def _start_run(question: str, approved_plan=None, label: str = "base", removed=None, axes=None) -> bool:
    """백그라운드 실행 시작. 이미 실행 중이면 False."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, done=False, queue=queue.Queue(), question=question,
                      removed=list(removed or []))
    threading.Thread(target=_run_target, args=(question, approved_plan, label, axes),
                     daemon=True).start()
    return True


@app.post("/run")
def start_run(body: dict):
    """질문을 받아 graph.run을 백그라운드 스레드로 시작 (동시 1개, 바쁘면 409)."""
    question = ((body or {}).get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question이 비어 있음")
    if not _start_run(question):
        raise HTTPException(409, "이미 실행 중")
    return {"started": True, "question": question}


@app.get("/events")
def events():
    """SSE: 큐의 로그 줄을 흘려보내고, 실행이 끝나면 event: done 후 종료."""

    def gen():
        with _lock:
            q = _state["queue"]
        if q is None:  # 아직 실행한 적 없음
            yield "event: done\ndata: done\n\n"
            return
        while True:
            try:
                yield f"data: {q.get(timeout=1.0)}\n\n"
            except queue.Empty:
                with _lock:
                    finished = _state["done"] and _state["queue"].empty()
                if finished:
                    yield "event: done\ndata: done\n\n"
                    return

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/result")
def result():
    """마지막으로 끝난 실행의 보고서 JSON."""
    with _lock:
        res = _state["result"]
        asked = _state["question"]
        removed = list(_state.get("removed", []))
    if res is None:
        raise HTTPException(404, "완료된 실행 없음")
    drafts = res.get("drafts", {})
    return {
        "question": res.get("question", asked),
        "report": res.get("report", ""),
        "plan": res.get("plan", []),
        "sections": {t: {"read": d.get("read", []), "text": d.get("text", "")}
                     for t, d in drafts.items()},
        "metrics": res.get("metrics", {}),
        "removed_sections": removed,
    }


@app.get("/doc/{title}")
def doc(title: str):
    """코퍼스 문서 앞 1500자 (없으면 404)."""
    docs = graph.load_corpus(graph.CFG["market"])["docs"]
    if title not in docs:
        raise HTTPException(404, "문서 없음")
    return {"title": title, "excerpt": docs[title][:1500]}


def _readiness() -> tuple:
    """코퍼스 + 업로드를 합쳐 stats/is_ready 계산 (디스크에 저장하지 않음)."""
    market = graph.CFG["market"]
    try:
        corpus = graph.load_corpus(market)
    except FileNotFoundError:
        corpus = {"docs": {}, "links": {}}
    uploads = collect.load_uploads(os.path.join(BASE, "data", market, "uploads"))
    docs = dict(corpus.get("docs", {}))
    docs.update(uploads)
    links = {t: [u for u in corpus.get("links", {}).get(t, []) if u in docs]
             for t in corpus.get("docs", {})}
    up_links = collect.build_links(docs)  # 업로드 문서는 제목-문자열 링크 (자기 것만)
    for t in uploads:
        links[t] = up_links[t]
    merged = {"docs": docs, "links": links}
    s = collect.stats(merged)
    ok, reason = collect.is_ready(merged)
    return s, ok, reason


@app.get("/state")
def state():
    """현재 대화 단계와 확정된 시장 정의 (+ 업로드용 market)."""
    return {"stage": _session["stage"], "scope": _session["scope"],
            "market": graph.CFG["market"]}


@app.post("/reset")
def reset():
    """대화를 처음(시장 정하기)부터 다시."""
    _session.update(stage="scope", scope="", turns=0, history=[], pending_choice=False,
                    pending_q="", pending_plan=[], pending_axes=[], removed=[])
    return state()


def _toc_reply(plan: list, alarms: list) -> str:
    """번호 매긴 목차 + 알람 + 확정 안내."""
    lines = [f"{i}. {p.get('title', '?')} — {p.get('role', '')} "
             f"(시작 문서: {p.get('seed') or '없음'})" for i, p in enumerate(plan, 1)]
    if _session["pending_axes"]:   # compare_table 켰을 때만 나온다
        lines.append("비교축: " + " · ".join(_session["pending_axes"]))
    lines += [f"! {a}" for a in (alarms or [])]
    lines.append("이대로 조사할까요? '예' / '빼기 2 4' (번호 빼기) / '다시' (목차 다시 짜기)")
    return "\n".join(lines)


@app.post("/chat")
def chat(body: dict):
    """단계별 대화: scope(시장 정하기) → upload(자료) → question(질문) → toc(목차 확인)."""
    text = ((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text가 비어 있음")
    stage = _session["stage"]

    if stage == "scope":  # 1. 시장 좁히기 (매 턴 LLM 후속 질문 1개, 정리: 면 2단계로)
        _session["turns"] += 1
        _session["history"].append(f"사용자: {text}")
        system = ("너는 시장조사 스코핑 봇이다. 아래 대화 기록을 보고 조사할 시장을 좁혀라"
                  "(지역, 세그먼트, 기간, 목적). 한 번에 짧은 후속 질문 하나만 하라. "
                  f"지금까지 사용자 답변 {_session['turns']}회. 충분히 좁혀졌거나 사용자 답변이 "
                  "3회를 넘기면 반드시 정확히 '정리: <한 줄 시장 정의>' 형식으로만 답하라.")
        reply = llm.ask(system, "\n".join(_session["history"]), coord=True).strip()
        _session["history"].append(f"봇: {reply}")
        if reply.startswith("정리:"):
            _session["scope"] = reply[len("정리:"):].strip()
            _session["stage"] = "upload"
            reply += ("\n시장조사에 쓸 자료가 있으면 이곳에 끌어다 놓아 주세요. "
                      "없으면 '없음'이라고 입력하세요.")
        return {"stage": _session["stage"], "reply": reply}

    if stage == "upload":  # 2. 자료 수집 + 준비도 확인
        if _session["pending_choice"]:
            if "웹검색" in text:
                _session["pending_choice"] = False
                _session["stage"] = "question"
                return {"stage": "question",
                        "reply": "웹 수집은 아직 준비 중입니다. 지금 자료로 진행합니다. 어떤 조사를 할까요?"}
            if "분석" in text:
                _session["pending_choice"] = False
                _session["stage"] = "question"
                return {"stage": "question",
                        "reply": "지금 자료로 진행합니다. 어떤 조사를 할까요?"}
            return {"stage": "upload",
                    "reply": "이 자료만으로 분석할까요, 웹에서 더 찾아볼까요? (분석 / 웹검색)"}
        if text in ("없음", "다음"):
            s, ok, reason = _readiness()
            if ok:
                _session["stage"] = "question"
                return {"stage": "question",
                        "reply": (f"이용할 준비가 되었습니다 "
                                  f"(문서 {s['doc_count']}건, {s['total_chars']}자). 어떤 조사를 할까요?"),
                        "stats": s}
            _session["pending_choice"] = True
            return {"stage": "upload",
                    "reply": (f"자료가 부족합니다 ({reason}). 이 자료만으로 분석할까요, "
                              "웹에서 더 찾아볼까요? (분석 / 웹검색)"),
                    "stats": s}
        return {"stage": "upload",
                "reply": "자료를 이곳에 끌어다 놓거나, 없으면 '없음'이라고 입력하세요."}

    # 3. 목차 확인 (동기 propose_plan; sync 엔드포인트는 FastAPI 스레드풀에서 돈다)
    if stage == "question":
        try:
            prop = graph.propose_plan(text)
        except Exception as e:
            return {"stage": "question",
                    "reply": f"목차를 짜는 데 실패했습니다 ({type(e).__name__}). 다시 질문해 주세요."}
        _session.update(pending_q=text, pending_plan=prop.get("plan", []), pending_axes=prop.get("axes", []),
                        removed=[], stage="toc")
        return {"stage": "toc",
                "reply": "조사하기 전에 목차를 확인하세요.\n"
                         + _toc_reply(_session["pending_plan"], prop.get("alarms", []))}

    # 4. 목차 확정/수정 (끝나면 다시 question 단계로)
    plan = _session["pending_plan"]
    t = text.strip()
    if t == "다시" or not plan:
        try:
            prop = graph.propose_plan(_session["pending_q"] or text)
        except Exception as e:
            return {"stage": "toc",
                    "reply": f"목차를 짜는 데 실패했습니다 ({type(e).__name__}). '다시'라고 입력해 주세요."}
        _session.update(pending_plan=prop.get("plan", []), pending_axes=prop.get("axes", []), removed=[])
        return {"stage": "toc", "reply": _toc_reply(_session["pending_plan"],
                                                    prop.get("alarms", []))}
    if t.lower() in ("예", "네", "ok"):
        if not _start_run(_session["pending_q"], approved_plan=plan, label="demo",
                          removed=_session["removed"], axes=_session["pending_axes"]):
            return {"stage": "toc", "reply": "이미 실행 중입니다. 끝나고 다시 답해 주세요."}
        _session["stage"] = "question"
        return {"stage": "question", "reply": "조사를 시작합니다.", "run": True}
    if t.startswith("빼기"):
        nums = sorted({int(n) for n in re.findall(r"\d+", t)}, reverse=True)
        if not nums or any(n < 1 or n > len(plan) for n in nums):
            return {"stage": "toc",
                    "reply": f"번호를 확인해 주세요 (1~{len(plan)}).\n" + _toc_reply(plan, [])}
        if len(nums) >= len(plan):
            return {"stage": "toc",
                    "reply": "전부 빼면 조사할 절이 없습니다. 최소 1개는 남겨 주세요.\n"
                             + _toc_reply(plan, [])}
        for n in nums:
            _session["removed"].append(plan.pop(n - 1).get("title", "?"))
        return {"stage": "toc", "reply": _toc_reply(plan, [])}
    return {"stage": "toc",
            "reply": "이대로 조사할까요? '예' / '빼기 2 4' (번호 빼기) / '다시' (목차 다시 짜기)\n"
                     + _toc_reply(plan, [])}
