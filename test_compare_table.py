"""비교표 LLM 없이 검사: llm.ask 를 가짜 응답으로 바꿔 카드 파싱 · 표 생성 · 실패 경보를 확인한다.
실행: python test_compare_table.py   (파일을 쓰지 않는다 — graph.run 대신 build().invoke)"""
import copy

import graph
import llm
import metrics

CARDS = {   # 절 제목 → 조사관 가짜 응답
    "LG": "LG는 1999년 배터리를 만들었다 «LG Chem».\n\n**[비교 카드]**\n- **시장 위치**: 세계 2위다 «LG Chem».\n"
          "- 차세대 기술: 자료 없음\n부족: 아니오",
    # 카드를 본문보다 먼저 씀 + 축 이름의 괄호를 줄여 씀 (실제 첫 실행에서 나온 모양) → 본문도 카드도 살아야
    "SK": "[비교 카드]\n시장 위치: 5위권이다 «SK Innovation».\n차세대 기술: 전고체를 연구한다 «SK Innovation».\n"
          "SK는 조지아에 공장이 있다 «SK Innovation».\n부족: 아니오",
    "삼성": "삼성은 원통형을 만든다 «Samsung SDI».\n부족: 아니오",     # 카드를 빼먹음 → 경보, 본문은 살아야
}


def fake_ask(system, user, coord=False):
    llm.USAGE["coord_chars" if coord else "sub_chars"] += len(system) + len(user)
    if "코디네이터" in system:
        assert ("비교축" in system) == SWITCH_ON          # 끄면 기획 프롬프트가 2차 실험과 같아야
        return ('{"목차":[{"절":"LG","시작문서":"LG Chem"},{"절":"SK","시작문서":"SK Innovation"},'
                '{"절":"삼성","시작문서":"Samsung SDI"}],"비교축":["시장 위치(점유율 순위)","차세대 기술"]}')
    if "비교표만 보고" in system:
        assert "[비교표]" in user and "1999년" not in user    # 편집자는 표만 본다 (본문 격리)
        return "LG는 2위, SK는 5위권이다 «LG Chem» «SK Innovation». 반면 «Tesla, Inc.»."
    if "편집자" in system:
        return "머리말.\n---\n맺음말."
    title = next(t for t in CARDS if f"'{t}' 절" in system)
    assert ("[비교 카드]" in system) == SWITCH_ON
    return CARDS[title]


def go(on: bool):
    global SWITCH_ON
    SWITCH_ON = on
    cfg = copy.deepcopy(graph.CFG)
    cfg["switches"]["compare_table"] = on
    return graph.build().invoke({"question": "3사 전략 차이?", "cfg": cfg, "corpus": graph.load_corpus(cfg["market"]),
                                 "drafts": {}, "alarms": []})


llm.ask = fake_ask

# 켰을 때: 카드 파싱 · 표 · 경보
out = go(True)
d = out["drafts"]
assert d["LG"]["card"] == {"시장 위치(점유율 순위)": "세계 2위다 «LG Chem».", "차세대 기술": "자료 없음"}
assert d["SK"]["text"] == "SK는 조지아에 공장이 있다 «SK Innovation»." and len(d["SK"]["card"]) == 2
assert d["LG"]["text"] == "LG는 1999년 배터리를 만들었다 «LG Chem»."          # 카드는 본문에서 빠진다
assert d["삼성"]["card"] is None and d["삼성"]["text"].startswith("삼성은")     # 카드 실패해도 본문은 산다
rep = out["report"]
assert rep.index("## 비교표") < rep.index("## 비교 요약") < rep.index("## LG") < rep.index("## 맺음말")
assert "| 시장 위치(점유율 순위) | 세계 2위다 «LG Chem». | 5위권이다 «SK Innovation». | (카드 없음) |" in rep
assert "비교 카드 없음: 삼성" in out["alarms"]
assert "비교 요약에 표에 없는 인용: ['Tesla, Inc.']" in out["alarms"]
# 표 칸은 칸마다 한 문장으로 센다: 머리 행·구분선·축 이름·'자료 없음'/'(카드 없음)' 칸은 뺀다
table = rep[rep.index("## 비교표"):rep.index("## 비교 요약")]
assert metrics.sentences(table) == ["세계 2위다 «LG Chem»", "5위권이다 «SK Innovation»", "전고체를 연구한다 «SK Innovation»"]

# 데모 경로: 사람이 확인한 목차 + 그때 나온 비교축을 넘기면 기획을 건너뛰고도 표가 나온다
cfg = copy.deepcopy(graph.CFG)
cfg["switches"]["compare_table"] = True
out = graph.build().invoke({"question": "3사 전략 차이?", "cfg": cfg, "corpus": graph.load_corpus(cfg["market"]),
                            "drafts": {}, "alarms": [], "axes": ["시장 위치(점유율 순위)", "차세대 기술"],
                            "plan": [{"title": t, "role": "조사관", "seed": None, "budget": 1} for t in ("LG", "SK")]})
assert "| 시장 위치(점유율 순위) | 세계 2위다 «LG Chem». | 5위권이다 «SK Innovation». |" in out["report"]

# 재위임: 채택 안 된 두 번째 원고도 원본 응답은 남는다 (0바퀴 빈 원고 추적용)
m = graph.keep_better({"A": {"text": "x «D».", "read": ["a"], "raw": "r0", "insufficient": True}},
                      {"A": {"text": "", "read": ["b"], "raw": "r1", "insufficient": True, "round": 1}})
assert m["A"]["text"] == "x «D»." and "r0" in m["A"]["raw"] and "r1" in m["A"]["raw"]

# 업로드 PDF: 쪽을 모아 DOC_CAP 이하 조각으로, 제목은 '파일명 p1-2' (마침표 없이)
import pathlib, tempfile, pymupdf
with tempfile.TemporaryDirectory() as tmp:
    pdf = pymupdf.open()
    for body in ["A" * 30, "B" * 30, "C" * 50]:
        pdf.new_page().insert_text((72, 72), body)
    pdf.save(pathlib.Path(tmp) / "rep.pdf")
    pathlib.Path(tmp, "note.txt").write_text("짧은 메모", encoding="utf-8")
    cap, graph.DOC_CAP = graph.DOC_CAP, 70
    got = dict(graph.upload_chunks(tmp, ("t",)))
    graph.DOC_CAP = cap
assert list(got) == ["note", "rep p1-2", "rep p3"], list(got)   # 30+30 ≤ 70 이라 한 조각, 50 은 넘쳐서 다음 조각
assert "A" * 30 in got["rep p1-2"] and "B" * 30 in got["rep p1-2"] and got["note"] == "짧은 메모"

# 껐을 때: 표 없음, 카드 없음, 보고서 모양은 예전 그대로
out = go(False)
assert "비교표" not in out["report"] and all(x["card"] is None for x in out["drafts"].values())
assert not any("카드" in a for a in out["alarms"])
print("test_compare_table OK")
