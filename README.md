# market-deep-researcher

시장조사용 딥리서치 에이전트. 코디네이터가 질문을 보고 목차를 짜서 절마다 서브에이전트를 동시에 보내고,
서브에이전트는 자기 절의 자료만 읽고 원고를 써서 올린다. 코디네이터는 원고를 다시 쓰지 않고 머리말·맺음말만 붙인다.

> 상태: **걸어 다니는 뼈대** — 그래프 연결·병렬 파견·재위임 루프·종합은 동작하고, 노드 안은 가짜 데이터다.

## 흐름

```mermaid
flowchart TD
    Q[질문] --> P[① 기획<br/>목차 · 역할 · 시작 자료 · 예산]
    P -->|Send| R1[③ 조사: 절 1]
    P -->|Send| R2[③ 조사: 절 2]
    P -->|Send| R3[③ 조사: 절 N]
    R1 & R2 & R3 --> C{④ 점검<br/>LLM 0회}
    C -->|부족 신고한 절만| R2
    C -->|충분 · 바퀴 소진 · 설정으로 끔| S[⑤ 종합<br/>머리말 · 맺음말만]
    S --> M[⑥ 측정<br/>정답표 없이]
```

웹 화면(예정): 왼쪽은 대화(시장 구체화 → 자료 업로드 → 준비 완료 → 질문 → 목차 확인), 오른쪽은 진행 과정.

## 실행

```bash
pip install -r requirements.txt
python graph.py "질문"          # 뼈대 한 바퀴
python collect.py data/<시장>/corpus.json   # 코퍼스 통계 · 준비 여부
uvicorn app:app --reload        # 웹 데모 (http://localhost:8000)
```

LLM 백엔드는 `config.json` 의 `backend` 로 고른다.
- `claude_sdk`: Claude Agent SDK. 로컬에 로그인된 Claude Code 계정으로 돈다
- `openai`: `OPENAI_API_KEY` 환경변수 필요. **키는 저장소에 올리지 않는다** (`.env` 는 gitignore)

## 구조

| 파일 | 역할 |
|---|---|
| `config.json` | 절수 상한 · 절예산 · 바퀴 상한 · 수집 파트 · 스위치 |
| `llm.py` | LLM 호출 단일 창구 + 코디네이터/서브에이전트 글자 수 계측 |
| `graph.py` | 기획 → 배치 → 조사 → 점검 → 종합 (LangGraph) |
| `collect.py` | 코퍼스 수집 · 링크 생성 · 준비 여부 판정 |
| `metrics.py` | 근거율 · 허위 인용 · 편중 · 중복률 · 숫자 불일치 · 격리율 |
| `ablation.py` | 스위치를 하나씩 끄고 재는 실험 |
| `baseline.py` | 혼자 하는 대조군 (같은 읽기 예산) |
| `app.py`, `static/` | 웹 데모 |
