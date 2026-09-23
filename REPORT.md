# REPORT

> 작성 중. 피어리뷰(2026-09-28) 이후 채운다.

## 1. 주제와 코퍼스

## 2. 분업 설계
- 수집 단계: 고정 파트(시장규모 · 경쟁사 · 규제 · 가격 · 소비자 · 유통)
- 조사 단계: 질문을 보고 **대상별**(회사 · 세그먼트 · 채널)로 목차를 나눈다

## 3. 지표
| 지표 | 종류 | 보는 장치 |
|---|---|---|
| 허위 인용 | 경보(0) | 그라운딩 |
| 숫자 불일치 | 경보(0) | 그라운딩 (인용은 붙었는데 숫자가 원문에 없음) |
| 인용 0개인 절 | 경보(0) | 역할 프롬프트 |
| 근거율 | 신호 | 역할 프롬프트 |
| 인용 편중 | 신호 | 절 폭 |
| 중복률 | 신호 | 배정 · 구역 |
| 격리율 | 신호 | 종합 구조 |

## 4. 파이프라인 구조도

```mermaid
flowchart TD
    START([질문 + cfg + corpus]) --> plan
    plan["① plan (코디네이터)<br/>문서 카드 150자만 보고 목차 작성<br/>시작문서가 코퍼스에 있는지 코드 검사"]
    plan -->|"Send × 절 수"| research
    research["③ research (서브에이전트, 병렬)<br/>pick_docs: 시작문서 → 링크 → 단어 겹침<br/>예산만큼 읽고 원고 + '부족: 예/아니오'"]
    research --> check
    check{"④ check (LLM 0회)<br/>부족 신고한 절이 있나?"}
    check -->|"있음 · 바퀴 남음 · 재위임 켜짐<br/>Send × 신고한 절만"| research
    check -->|"내용 충분 / 바퀴 소진 / 설정으로 끔"| synthesize
    synthesize["⑤ synthesize (코디네이터)<br/>절 제목만 보고 머리말·맺음말<br/>절 본문은 손대지 않음"]
    synthesize --> END([report])
    END --> metrics["⑥ metrics.compute<br/>정답표·판정모델 없이"]
```

| State 필드 | 리듀서 | 누가 쓰나 |
|---|---|---|
| `plan` | 덮어쓰기 | plan |
| `drafts` | `keep_better` — 재위임 원고는 인용 수가 첫 원고 이상일 때만 채택, 읽은 기록은 누적 | research |
| `round`, `stop_reason` | 덮어쓰기 | plan, check |
| `alarms`, `log` | 이어 붙이기 | plan / 전 노드 |

격리 측정: `llm.ask(coord=True/False)` 가 코디네이터와 서브에이전트가 받은 글자를 따로 센다 → `isolation = coord / (coord + sub)`.

## 5. 데모 설계

## 6. 회고
