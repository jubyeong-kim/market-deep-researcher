"""FastAPI 앱. 실행: uvicorn app:app --reload"""
import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

BASE = Path(__file__).parent
app = FastAPI()


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


@app.get("/events")
async def events():
    """SSE 데모: 5개 이벤트를 1초 간격으로 보내고 종료."""
    stages = ["기획", "배치", "조사", "점검", "종합"]

    async def gen():
        for s in stages:
            yield f"data: {s}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")
