"""기획 -> 배치(Send) -> 조사 -> 점검 -> (재위임 | 종합) -> 측정

실행: python graph.py "질문" [라벨] [켤 스위치...]
설정은 config.json. 실험(ablation)은 run(question, cfg) 에 스위치를 바꾼 cfg 를 넘긴다.
"""
import copy
import json
import operator
import re
import sys
import time
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

import llm
import metrics

BASE = Path(__file__).parent
CFG = json.load(open(BASE / "config.json", encoding="utf-8"))
DOC_CAP = 6000      # 문서 한 건에서 서브에이전트가 읽는 최대 글자
CARD_LEN = 150      # 코디네이터가 보는 문서 카드 길이


def load_corpus(market):
    return json.load(open(BASE / "data" / market / "corpus.json", encoding="utf-8"))


def n_citations(text: str) -> int:
    return len(re.findall(r"«[^»]+»", text))


def keep_better(old: dict, new: dict) -> dict:
    """재위임 원고는 인용 수가 첫 원고 이상일 때만 채택.
    무조건 덮어쓰면 인용을 빠뜨린 두 번째 원고가 멀쩡한 첫 원고를 지운다.
    읽은 기록(read)은 채택 여부와 상관없이 누적한다 — 실제로 읽었으니까."""
    merged = dict(old)
    for title, d in new.items():
        prev = merged.get(title)
        if prev is None or n_citations(d["text"]) >= n_citations(prev["text"]):
            merged[title] = d
        else:
            merged[title] = {**prev, "insufficient": d["insufficient"], "rejected": d["text"]}
        if prev:
            # 모델 원본 응답도 바퀴마다 누적 — 덮어쓰면 0바퀴 빈 원고의 원인을 추적할 수 없다 (비교표 첫 실행에서 겪음)
            merged[title]["raw"] = prev.get("raw", "") + f"\n\n<!-- {d.get('round')}바퀴 -->\n" + d.get("raw", "")
            merged[title]["read"] = prev["read"] + [r for r in d["read"] if r not in prev["read"]]
            merged[title]["attempts"] = prev.get("attempts", 0) + d.get("attempts", 0)
    return merged


class State(TypedDict, total=False):
    question: str
    cfg: dict
    corpus: dict
    plan: list            # [{title, role, seed, budget}]
    axes: list            # 비교축 (compare_table 켰을 때만). 절들이 같은 축으로 카드를 쓴다
    alarms: Annotated[list, operator.add]
    drafts: Annotated[dict, keep_better]   # 절 -> {text, card, insufficient, read, attempts}
    round: int
    stop_reason: str
    report: str
    log: Annotated[list, operator.add]


def parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


# ① 기획 — 코디네이터는 문서 카드(앞 CARD_LEN자)만 보고 목차·역할·시작자료·예산을 정한다
def plan(s: State):
    if s.get("plan"):   # 데모에서 사람이 확인·수정한 목차를 넘긴 경우 — 다시 짜지 않는다
        return {"round": 0, "log": [f"기획: 사람이 확정한 목차 {len(s['plan'])}개 — " +
                                    ", ".join(p["title"] for p in s["plan"])]}
    cfg, docs = s["cfg"], s["corpus"]["docs"]
    cards = "\n".join(f"- {t}: {v[:CARD_LEN].replace(chr(10), ' ')}" for t, v in docs.items())
    system = ("너는 시장조사 팀의 코디네이터다. 질문에 답할 보고서 목차를 짜라. "
              f"절은 최대 {cfg['max_sections']}개지만 질문이 실제로 나뉘는 만큼만 나눠라 — 칸을 채우려고 절을 만들지 마라. "
              "목차는 형식(개요·분석·전망)이 아니라 조사 대상(회사·세그먼트·채널·기술 등) 단위로 나눠라. "
              "절마다 역할과, 가장 먼저 읽을 문서(아래 목록의 제목 그대로)를 하나씩 배정하라. 절끼리 시작 문서가 겹치면 안 된다. "
              "문서는 영어이므로 절마다 문서를 찾을 영어 검색어 3~5개도 적어라. "
              'JSON으로만 답하라: {"목차":[{"절":"...","역할":"...","시작문서":"...","검색어":["..."]}]}')
    if cfg["switches"]["compare_table"]:   # 끄면 위 프롬프트 그대로 → 2차 실험 54회와 같은 조건
        # 첫 실행에서 이 요청이 목차까지 기능별(기술/고객/ESS)로 끌고 감 → 목차와 별개임을 못 박는다
        system += (" 또 절들을 나란히 견줄 공통 비교축 3~5개를 정하라 (예: 시장 위치, 차세대 기술, 고객사, 생산기지). "
                   "비교축은 목차가 아니다 — 목차는 위 규칙대로 조사 대상 단위로 나누고, 비교축은 그 절들을 같은 기준으로 견줄 항목이다. "
                   "축 이름은 괄호 없이 짧게. 절끼리 견줄 질문이 아니면 빈 목록. "
                   '형식: {"목차":[위와 같음],"비교축":["...","..."]}')
    out = parse_json(llm.ask(system, f"[질문] {s['question']}\n[문서 카드]\n{cards}", coord=True))
    axes = [a.strip() for a in out.get("비교축") or [] if isinstance(a, str) and a.strip()][:5] \
        if cfg["switches"]["compare_table"] else []
    sections, alarms, taken = [], [], set()
    for x in out.get("목차", [])[: cfg["max_sections"]]:
        seed = x.get("시작문서", "")
        if seed not in docs or seed in taken:          # 모델은 그럴듯한 제목을 지어낸다 → 코드가 검사
            alarms.append(f"시작문서 무효: '{seed}' (절: {x.get('절')})")
            seed = None                                  # 조용히 대체하지 않는다
        if not cfg["switches"]["assignment"]:
            seed = None
        taken.add(seed)
        sections.append({"title": x.get("절", "?"), "role": x.get("역할", "조사관"),
                         "seed": seed, "budget": cfg["section_budget"], "keywords": x.get("검색어", [])})
    if not sections:
        alarms.append("목차 생성 실패")
    return {"plan": sections, "axes": axes, "round": 0, "alarms": alarms,
            "log": [f"기획: 절 {len(sections)}개 — " + ", ".join(p["title"] for p in sections)
                    + (f" · 비교축 {axes}" if axes else "")]}


# ② 배치 — 절마다 서브에이전트를 동시에 파견, 남의 구역(절 제목·시작문서)을 알려 줌
def dispatch(s: State):
    todo = [p for p in s["plan"] if s["round"] == 0 or s["drafts"].get(p["title"], {}).get("insufficient")]
    picks = {}
    if s["cfg"]["switches"]["zones"]:
        # 구역: 병렬 조사관은 서로를 못 봐서 같은 인기 문서로 몰린다 → 파견 전에 코드가 겹치지 않게 나눠 준다 (LLM 0회)
        corpus = s["corpus"]
        taken = {r for d in s["drafts"].values() for r in d["read"]} | {p["seed"] for p in s["plan"] if p["seed"]}
        for p in todo:
            already = s["drafts"].get(p["title"], {}).get("read", [])
            own_seed = {p["seed"]} if p["seed"] and p["seed"] not in already else set()
            picks[p["title"]] = pick_docs(p, corpus["docs"], corpus["links"], taken - own_seed, already,
                                          p["budget"], s["cfg"]["switches"]["links"])
            taken |= set(picks[p["title"]])
    return [Send("research", {
        "picks": picks.get(p["title"]),
        "section": p, "question": s["question"], "cfg": s["cfg"], "corpus": s["corpus"], "round": s["round"],
        "axes": s.get("axes") or [],
        "others": [(q["title"], q["seed"]) for q in s["plan"] if q is not p],
        "others_read": [r for t, d in s["drafts"].items() if t != p["title"] for r in d["read"]],
        "already": s["drafts"].get(p["title"], {}).get("read", []),
    }) for p in todo]


def pick_docs(sec, docs, links, avoid, already, budget, use_links):
    """다음에 읽을 문서를 코드가 고른다: 시작문서 → 읽은 문서의 링크 → 절 제목 단어가 겹치는 문서.
    ponytail: LLM에게 고르게 하면 절마다 호출이 예산만큼 늘어난다. 링크+단어 겹침으로 대신함. 품질 부족하면 LLM 선택으로 교체."""
    # 절 제목은 한국어, 문서는 영어 → 코디네이터가 준 영어 검색어로 점수를 매긴다
    words = [w.lower() for w in re.split(r"\W+", sec["title"]) + sec.get("keywords", []) if len(w) >= 2]
    score = lambda t: sum(w in t.lower() or w in docs[t][:2000].lower() for w in words)
    chosen = [sec["seed"]] if sec["seed"] and sec["seed"] not in already else []
    while len(chosen) < budget:
        seen = set(already) | set(chosen)
        linked = {t for r in (list(already) + chosen) for t in links.get(r, [])} if use_links else set()
        pool = [t for t in docs if t not in seen and t not in avoid]
        if not pool:
            break
        # 검색어 점수가 먼저, 링크는 동점일 때만 — 링크를 무조건 앞세우면 무관한 문서(허브 문서)로 샌다
        chosen.append(max(pool, key=lambda t: (score(t), t in linked)))
    return chosen


# ③ 조사 — 자기 절 자료만 읽고 원고까지 써서 올림 (원문은 여기서 소화되고 위로는 원고만)
def research(task: dict):
    sec, cfg, corpus = task["section"], task["cfg"], task["corpus"]
    docs = corpus["docs"]
    # 구역: 남의 시작문서 + (재위임 바퀴라면) 남이 이미 읽은 문서는 피한다
    avoid = ({seed for _, seed in task["others"] if seed} | set(task["others_read"])) \
        if cfg["switches"]["zones"] else set()
    read = task["picks"] if task["picks"] is not None else \
        pick_docs(sec, docs, corpus["links"], avoid, task["already"], sec["budget"], cfg["switches"]["links"])
    material = "\n\n".join(f"### «{t}»\n{docs[t][:DOC_CAP]}" for t in read)
    zones = "; ".join(t for t, _ in task["others"]) if cfg["switches"]["zones"] else "(알려주지 않음)"
    system = (f"너는 시장조사 팀의 {sec['role']}다. 보고서의 '{sec['title']}' 절 하나만 쓴다. "
              f"다른 조사관이 맡은 절: {zones} — 그 내용은 쓰지 마라. "
              "아래 자료에 있는 내용만 쓰고, 모든 문장 끝에 근거 문서를 «문서제목» 형식으로 붙여라. 자료에 없는 숫자는 쓰지 마라. "
              "인용은 문장의 마침표 바로 앞에 붙여라 (예: ...생산했다 «LG Chem».). 문장 앞이나 마침표 뒤에 두지 마라. "
              "제목·구분선(---)·인사말·'작성하겠습니다' 같은 설명 없이 바로 본문 문단만 써라. 자료가 모자라도 불평하지 말고 있는 만큼 써라. "
              "마지막 줄에만 '부족: 예' 또는 '부족: 아니오'를 적어라. '예'는 이 절의 핵심 질문에 답할 사실이 자료에 거의 없을 때만이다 — "
              "세부 수치나 최신 정보가 없는 정도로는 '아니오'.")
    axes = task.get("axes") or []
    if axes:   # 비교 카드: 편집자가 본문을 안 읽고도 절끼리 견줄 수 있게, 같은 축으로 한 줄씩
        system += (" 본문 다음, '부족' 줄 앞에 '[비교 카드]' 한 줄을 쓰고, 아래 비교축마다 한 줄씩 "
                   "'축이름: 이 절 대상의 해당 사실 한 문장 «문서제목»' 형식으로 적어라. 자료에 없으면 '축이름: 자료 없음'. "
                   f"비교축: {' / '.join(axes)}")
    out = llm.ask(system, f"[질문] {task['question']}\n[자료]\n{material or '(없음)'}", coord=False)
    insufficient = bool(re.search(r"부족\s*:\s*예", out))
    body, card, alarms = parse_card(out, axes, sec["title"])
    # 신고 표시만 지운다 — 줄째 지우면 같은 줄에 쓴 본문까지 날아간다 (Q3 빈 절 추적 중 발견)
    text = re.sub(r"[(\[]?부족\s*:\s*(예|아니오)[)\]]?\.?", "", body)
    text = re.sub(r"^\s*(#.*|-{3,})\s*$", "", text, flags=re.M).strip()   # 모델이 붙인 제목·구분선 제거
    if not text:                          # 빈 원고는 조용히 넘기지 않는다: 경보 + 부족 처리 (재위임 대상)
        insufficient = True
        alarms.append(f"빈 원고: {sec['title']} ({task['round']}바퀴, 읽음 {read})")
    return {"drafts": {sec["title"]: {"text": text, "card": card, "insufficient": insufficient, "read": read,
                                      "raw": out, "attempts": len(read), "round": task["round"]}},
            "alarms": alarms,
            "log": [f"조사: {sec['title']} ({task['round']}바퀴) 읽음 {read}"
                    f"{' · 부족 신고' if insufficient else ''}{' · 빈 원고' if not text else ''}"]}


def parse_card(out: str, axes: list, title: str):
    """원고에서 '[비교 카드]' 줄 뒤의 '축: 한 줄' 들을 떼어 {축: 한 줄} 로. 반환: (본문, 카드|None, 경보).
    카드 줄만 빼고 나머지는 전부 본문으로 남긴다 — 모델이 카드를 본문 앞에 써도 본문이 안 날아간다.
    축 이름은 괄호 앞까지만 맞춘다 (첫 실행에서 모델이 '기술 포지셔닝(고성능 vs …)'을 '기술 포지셔닝'으로 줄여 써서 칸이 비었음)."""
    if not axes:
        return out, None, []
    lines = out.splitlines()
    at = next((i for i, l in enumerate(lines) if re.search(r"비교\s*카드", l)), None)   # '**[비교 카드]**' 도
    if at is None:
        return out, None, [f"비교 카드 없음: {title}"]
    head = lambda x: re.sub(r"[\s*#\[\]-]", "", x.split("(")[0])
    card, body = {}, lines[:at]
    for line in lines[at + 1:]:
        k, sep, v = line.partition(":")
        a = next((a for a in axes if head(a) == head(k)), None)
        if sep and a and a not in card:
            card[a] = v.strip()
        else:
            body.append(line)
    missing = [a for a in axes if a not in card]
    return "\n".join(body), card, ([f"비교 카드 축 빠짐: {title} — {missing}"] if missing else [])


# ④ 점검 — LLM 호출 0회. 부족 신고한 절만 다시 내보내고, 멈춘 이유를 남긴다
def check(s: State):
    flagged = [t for t, d in s["drafts"].items() if d.get("insufficient")]
    nxt = s["round"] + 1
    if not flagged:
        reason = "내용 충분"
    elif not s["cfg"]["switches"]["redelegation"]:
        reason = "설정으로 끔"
    elif nxt >= s["cfg"]["max_rounds"]:
        reason = "바퀴 소진"
    else:
        reason = ""
    return {"round": nxt, "stop_reason": reason, "log": [f"점검: 부족 {flagged} → {reason or '재위임'}"]}


def after_check(s: State):
    return "synthesize" if s["stop_reason"] else dispatch(s)


# ⑤ 종합 — 코디네이터는 절 제목만 보고 머리말·맺음말을 쓴다. 절 본문은 손대지 않는다(격리 유지, 인용 보존)
def synthesize(s: State):
    # 인용이 하나도 없는 절(빈 원고 포함)은 본문에서 빼고 맺음말에 밝힌다 — 빈 제목만 남기면 보고서가 멀쩡해 보인다.
    # 2차 실험의 빈 절 15건은 전부 '고객·글로벌·규제' 같은 밖으로 벌린 절이었고, 읽은 문서가 절 주인공을 다루지 않았다.
    all_titles = [p["title"] for p in s["plan"]]
    titles = [t for t in all_titles if t in s["drafts"] and n_citations(s["drafts"][t]["text"]) > 0]
    dropped = [t for t in all_titles if t not in titles]
    system = ("너는 시장조사 보고서 편집자다. 절 본문은 이미 있다. 질문과 절 제목만 보고 "
              "머리말(보고서가 무엇을 어떤 순서로 다루는지, 2~3문장)과 맺음말(더 조사할 점, 1~2문장)만 써라. "
              "숫자나 사실 주장은 쓰지 마라. '작성하겠습니다' 같은 설명 없이 바로 본문만. 형식: 머리말 본문, 줄바꿈 후 '---', 줄바꿈 후 맺음말 본문.")
    out = llm.ask(system, f"[질문] {s['question']}\n[절] " + " / ".join(titles), coord=True)
    head, _, foot = out.partition("---")
    body = "\n\n".join(f"## {t}\n{s['drafts'][t]['text']}" for t in titles)
    note = (f"\n\n자료 부족으로 다루지 못한 절: {', '.join(dropped)} (조사관이 읽은 문서에 근거가 없었음)" if dropped else "")
    compare, alarms = compare_table(s, titles)
    return {"report": f"# {s['question']}\n\n{head.strip()}\n\n{compare}{body}\n\n## 맺음말\n{foot.strip()}{note}",
            "alarms": [f"보고서에서 뺀 절: {t}" for t in dropped] + alarms,
            "log": ["종합 완료" + (f" (근거 없는 절 {len(dropped)}개 제외)" if dropped else "")
                    + (" · 비교표" if compare else "")]}


def compare_table(s: State, titles: list):
    """비교표는 코드가 카드로 만든다 (행=비교축, 열=절, 칸=카드 한 줄 그대로 — 인용 보존).
    편집자는 절 본문 대신 이 표만 보고 비교 요약을 쓴다 → 격리는 표 크기만큼만 깨진다. 반환: (보고서 조각, 경보)"""
    axes = s.get("axes") or []
    cards = {t: s["drafts"][t].get("card") or {} for t in titles}
    if not s["cfg"]["switches"]["compare_table"] or not axes or sum(bool(c) for c in cards.values()) < 2:
        return "", []                                    # 견줄 카드가 두 장 이상일 때만
    cell = lambda v: str(v).replace("|", "｜").replace("\n", " ")
    rows = ["| 비교축 | " + " | ".join(map(cell, titles)) + " |", "|" + "---|" * (len(titles) + 1)]
    rows += ["| " + cell(a) + " | " + " | ".join(cell(cards[t].get(a, "(카드 없음)")) for t in titles) + " |"
             for a in axes]
    table = "\n".join(rows)
    system = ("너는 시장조사 보고서 편집자다. 아래 비교표만 보고 열(절)끼리 견주는 '비교 요약'을 3~5문장으로 써라. "
              "표에 있는 사실만 쓰고, 문장마다 그 사실이 있던 칸의 «문서제목»을 그대로 붙여라 (마침표 바로 앞). "
              "표에 없는 인용·숫자·평가는 쓰지 마라. '자료 없음'·'(카드 없음)' 칸은 견주지 마라. 제목·설명 없이 문장만.")
    summary = llm.ask(system, f"[질문] {s['question']}\n[비교표]\n{table}", coord=True)
    summary = re.sub(r"^\s*(#.*|-{3,})\s*$", "", summary, flags=re.M).strip()
    extra = sorted(set(metrics.citations(summary)) - set(metrics.citations(table)))   # 편집자가 표 밖에서 가져온 인용
    return (f"## 비교표\n{table}\n\n## 비교 요약\n{summary}\n\n",
            [f"비교 요약에 표에 없는 인용: {extra}"] if extra else [])


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


def propose_plan(question: str, cfg: dict = None) -> dict:
    """목차만 뽑는다 (데모의 목차 확인 단계용). 반환: {plan, alarms, log}. 이 호출의 글자 수는 run(approved_plan=...)이 이어받는다."""
    cfg = cfg or CFG
    for k in llm.USAGE:
        llm.USAGE[k] = 0
    return plan({"question": question, "cfg": cfg, "corpus": load_corpus(cfg["market"])})


def run(question: str, cfg: dict = None, label: str = "base", on_log=print, approved_plan: list = None) -> dict:
    """한 번 돌리고 output/runs/<시각>_<라벨>/ 에 목차·원고·읽은 기록·보고서·지표를 남긴다."""
    cfg = cfg or CFG
    corpus = load_corpus(cfg["market"])
    if not approved_plan:            # 목차를 propose_plan 으로 미리 뽑았다면 그 글자 수를 이어서 센다
        for k in llm.USAGE:
            llm.USAGE[k] = 0
    t0 = time.time()
    out, n = {}, 0
    init = {"question": question, "cfg": cfg, "corpus": corpus, "drafts": {}, "alarms": []}
    if approved_plan:
        init["plan"] = approved_plan
    for out in build().stream(init, stream_mode="values"):
        for line in out.get("log", [])[n:]:
            on_log(line)                      # 웹 화면 진행 패널로 흘려보낼 자리
        n = len(out.get("log", []))
    drafts = out["drafts"]
    visited = {t for d in drafts.values() for t in d["read"]}
    m = metrics.compute(out["report"], visited, corpus["docs"], sum(d["attempts"] for d in drafts.values()),
                        llm.USAGE["coord_chars"], llm.USAGE["sub_chars"])
    m.update(alarms=out["alarms"], stop_reason=out["stop_reason"], calls=llm.USAGE["calls"],
             coord_chars=llm.USAGE["coord_chars"], sub_chars=llm.USAGE["sub_chars"],
             empty_sections=[t for t, d in drafts.items() if n_citations(d["text"]) == 0],
             seconds=round(time.time() - t0, 1))
    d = BASE / "output" / "runs" / f"{time.strftime('%m%d-%H%M%S')}_{label}"
    (d / "sections").mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (d / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    dump("plan.json", out["plan"])
    dump("visited.json", {t: x["read"] for t, x in drafts.items()})
    dump("metrics.json", m)
    if out.get("axes"):
        dump("cards.json", {"axes": out["axes"], "cards": {t: x.get("card") for t, x in drafts.items()}})
    for t, x in drafts.items():
        name = re.sub(r'[^0-9A-Za-z가-힣]+', '_', t)
        (d / "sections" / f"{name}.md").write_text(
            x["text"] + (f"\n\n<!-- 채택 안 된 재위임 원고 -->\n{x['rejected']}" if x.get("rejected") else ""),
            encoding="utf-8")
        (d / "sections" / f"{name}.raw.txt").write_text(x.get("raw", ""), encoding="utf-8")   # 정리 전 모델 응답
    (d / "report.md").write_text(out["report"], encoding="utf-8")
    with open(BASE / "output" / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"dir": d.name, "question": question, "label": label,
                            **{k: v for k, v in m.items() if k != "citation_list"}}, ensure_ascii=False) + "\n")
    return {**out, "metrics": m, "dir": str(d)}


if __name__ == "__main__":
    # python graph.py "질문" 라벨 [켤 스위치...]   예) python graph.py "..." compare_table compare_table
    q = sys.argv[1] if len(sys.argv) > 1 else "국내외 배터리 3사의 전략 차이는?"
    cfg = copy.deepcopy(CFG)
    for sw in sys.argv[3:]:
        assert sw in cfg["switches"], f"없는 스위치: {sw}"
        cfg["switches"][sw] = True
    r = run(q, cfg, label=sys.argv[2] if len(sys.argv) > 2 else "base")
    print(json.dumps({k: v for k, v in r["metrics"].items() if k not in ("citation_list", "number_mismatch")},
                     ensure_ascii=False, indent=1))
    print("저장:", r["dir"])
