"""어블레이션 스텁.

SWITCHES 중 하나씩 기능을 끄고 전체 파이프라인을 반복 실행해
각 기능의 기여도를 측정한다. 결과는 output/ablation.json에 저장.
아직 미구현.
"""

SWITCHES = ["assignment", "zones", "redelegation", "links"]


def run_ablation(questions: list, cfg: dict, corpus: dict, repeats: int = 3):
    """스위치를 하나씩 끈 채로 repeats회 반복 실행 (미구현)."""
    raise NotImplementedError("ablation: TODO (output/ablation.json 저장)")
