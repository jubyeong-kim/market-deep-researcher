"""기획 -> 배치(Send) -> 조사 -> 점검 -> (재위임 | 종합)

지금은 걸어 다니는 뼈대: 노드 안은 가짜 데이터(TODO), 연결·팬아웃·재위임 루프·종합은 실제로 돈다.
실행: python graph.py "질문"
"""
import json
import operator
import re
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

CFG = json.load(open(Path(__file__).with_name("config.json"), encoding="utf-8"))


def n_citations(text: str) -> int:
    return len(re.findall(r"«[^»]+»", text))


def keep_better(old: dict, new: dict) -> dict:
    """재위임 원고는 인용 수가 첫 원고 이상일 때만 채택.
    무조건 덮어쓰면 인용을 빠뜨린 두 번째 원고가 멀쩡한 첫 원고를 지운다."""
    merged = dict(old)
    for title, d in new.items():
        if title not in merged or n_citations(d["text"]) >= n_citations(merged[title]["text"]):
            merged[title] = d
    return merged


class State(TypedDict, total=False):
    question: str
    plan: list            # [{title, role, seed, budget}]
    drafts: Annotated[dict, keep_better]   # title -> {text, insufficient, read}
    round: int
    stop_reason: str
    report: str
    log: Annotated[list, operator.add]


# ① 기획 — 코디네이터가 목차를 짜고 절마다 역할·시작자료·예산 배정
def plan(s: State):
    # TODO(목): llm.ask(coord=True)로 목차 생성 + 시작자료가 코퍼스에 있는지 코드 검사
    sections = [
        {"title": "A사", "role": "경쟁사 분석가", "seed": "문서1", "budget": CFG["section_budget"]},
        {"title": "B사", "role": "경쟁사 분석가", "seed": "문서2", "budget": CFG["section_budget"]},
        {"title": "유통 채널", "role": "유통 분석가", "seed": "문서3", "budget": CFG["section_budget"]},
    ][: CFG["max_sections"]]
    return {"plan": sections, "round": 0, "log": [f"기획: 절 {len(sections)}개"]}


# ② 배치 — 절마다 서브에이전트를 동시에 파견, 남의 구역을 알려 줌
def dispatch(s: State):
    todo = [p for p in s["plan"]
            if s["round"] == 0 or s["drafts"].get(p["title"], {}).get("insufficient")]
    return [Send("research", {"section": p, "others": [q["title"] for q in s["plan"] if q is not p],
                              "round": s["round"]}) for p in todo]


# ③ 조사 — 자기 절만 읽고 원고까지 써서 올림 (원문은 여기서 소화되고 위로는 원고만)
def research(task: dict):
    # TODO(목): read_doc 도구로 예산만큼 읽고 링크 타기, llm.ask(coord=False)로 원고 작성
    t, r = task["section"]["title"], task["round"]
    fake_insufficient = (t == "B사" and r == 0)   # 재위임 루프가 도는지 보려고 한 절만 부족 신고
    text = f"{t} 관련 가짜 원고 {r}바퀴. «{task['section']['seed']}»"
    return {"drafts": {t: {"text": text, "insufficient": fake_insufficient, "read": [task["section"]["seed"]]}},
            "log": [f"조사: {t} ({r}바퀴{', 부족 신고' if fake_insufficient else ''})"]}


# ④ 점검 — LLM 호출 0회. 부족 신고한 절만 다시 내보내고, 멈춘 이유를 남긴다
def check(s: State):
    flagged = [t for t, d in s["drafts"].items() if d.get("insufficient")]
    nxt = s["round"] + 1
    if not flagged:
        reason = "내용 충분"
    elif not CFG["switches"]["redelegation"]:
        reason = "설정으로 끔"
    elif nxt >= CFG["max_rounds"]:
        reason = "바퀴 소진"
    else:
        reason = ""
    return {"round": nxt, "stop_reason": reason, "log": [f"점검: 부족 {flagged} → {reason or '재위임'}"]}


def after_check(s: State):
    return "synthesize" if s["stop_reason"] else dispatch(s)


# ⑤ 종합 — 절 본문은 손대지 않고 머리말·맺음말만
def synthesize(s: State):
    # TODO(목): 머리말·맺음말만 llm.ask(coord=True). 절 본문은 코디네이터에게 보내지 않는다
    body = "\n\n".join(f"## {p['title']}\n{s['drafts'][p['title']]['text']}" for p in s["plan"])
    report = f"# {s['question']}\n\n(머리말)\n\n{body}\n\n(맺음말)"
    return {"report": report, "log": ["종합 완료"]}


def build():
    g = StateGraph(State)
    g.add_node("plan", plan)
    g.add_node("research", research)
    g.add_node("check", check)
    g.add_node("synthesize", synthesize)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", dispatch, ["research"])
    g.add_edge("research", "check")
    g.add_conditional_edges("check", after_check, ["research", "synthesize"])
    g.add_edge("synthesize", END)
    return g.compile()


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "국내 시장 주요 업체들의 전략 차이는?"
    out = build().invoke({"question": q, "drafts": {}})
    print("\n".join(out["log"]))
    print("멈춘 이유:", out["stop_reason"])
    print(out["report"])
    assert out["stop_reason"] == "내용 충분" and "1바퀴" in out["drafts"]["B사"]["text"]
