"""FastAPI 앱. 실행: uvicorn app:app --reload"""
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

import graph

BASE = Path(__file__).parent
app = FastAPI()

_state = {"running": False, "done": False, "queue": None, "result": None, "question": ""}
_lock = threading.Lock()


def _push(line: str) -> None:
    q = _state["queue"]
    if q is not None:
        q.put(str(line).replace("\r", "").replace("\n", " "))


def _run_target(question: str) -> None:
    try:
        res = graph.run(question, label="base", on_log=_push)
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
    import os
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


@app.post("/run")
def start_run(body: dict):
    """질문을 받아 graph.run을 백그라운드 스레드로 시작 (동시 1개, 바쁘면 409)."""
    question = ((body or {}).get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question이 비어 있음")
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "이미 실행 중")
        _state.update(running=True, done=False, queue=queue.Queue(), question=question)
    threading.Thread(target=_run_target, args=(question,), daemon=True).start()
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
    }


@app.get("/doc/{title}")
def doc(title: str):
    """코퍼스 문서 앞 1500자 (없으면 404)."""
    docs = graph.load_corpus(graph.CFG["market"])["docs"]
    if title not in docs:
        raise HTTPException(404, "문서 없음")
    return {"title": title, "excerpt": docs[title][:1500]}
