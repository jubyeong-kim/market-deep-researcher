"""LLM 호출은 전부 여기 ask() 하나로 모은다.
backend 교체(claude_sdk -> openai)는 config.json 한 줄로 끝나고,
누가 몇 글자를 봤는지(격리 측정)도 여기서 센다."""
import json
import anyio

from pathlib import Path

CFG = json.load(open(Path(__file__).with_name("config.json"), encoding="utf-8"))
USAGE = {"coord_chars": 0, "sub_chars": 0, "calls": 0}


def ask(system: str, user: str, coord: bool = False) -> str:
    """coord=True 면 코디네이터가 본 글자, 아니면 서브에이전트가 본 글자로 센다."""
    USAGE["coord_chars" if coord else "sub_chars"] += len(system) + len(user)
    USAGE["calls"] += 1
    backend = CFG["backend"]
    model = CFG["model"][backend]
    if backend == "claude_sdk":
        return anyio.run(_ask_claude, system, user, model)
    if backend == "openai":
        from openai import OpenAI  # OPENAI_API_KEY 환경변수 필요
        r = OpenAI().chat.completions.create(
            model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content
    if backend == "opencode":
        # 개발용 무료 백엔드(느림, 호출당 ~40초). opencode 는 에이전트라 파일을 건드릴 수 있어 빈 임시 폴더에서 돌린다
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(["opencode", "run", "-m", model, f"{system}\n\n{user}"], cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", timeout=300)
        return r.stdout.strip()
    raise ValueError(f"unknown backend: {backend}")


def search(system: str, user: str) -> str:
    """웹 검색 (스위치 web_search 만). 도구는 이 호출에만 준다 — 원고를 쓰는 ask() 는 계속 tools=[].
    모델은 URL 만 고르고, 본문은 코드가 받아 저장한다 (인용을 읽은 글과 대조하려고). 조사관 쪽 글자로 센다"""
    USAGE["sub_chars"] += len(system) + len(user)
    USAGE["calls"] += 1
    if CFG["backend"] != "claude_sdk":
        raise ValueError("web_search 는 claude_sdk 백엔드에서만 된다")
    return anyio.run(_ask_claude, system, user, CFG["model"]["claude_sdk"], ["WebSearch"])


async def _ask_claude(system, user, model, tools=()):
    # 구독 로그인(Claude Code)으로 돈다. system_prompt 를 직접 주면 기본 프롬프트(~2만 토큰)가 빠진다.
    # tools=[] 로 내장 도구를 아예 끈다 (allowed_tools=[] 는 자동승인 목록일 뿐이라 모델이 도구를 부르면 1턴 제한에 걸림)
    # 검색(search)만 WebSearch 를 켜고 턴을 늘린다 (검색 → 답)
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    opts = ClaudeAgentOptions(model=model, system_prompt=system, max_turns=4 if tools else 1,
                              tools=list(tools), allowed_tools=list(tools), setting_sources=[])
    for attempt in range(2):
        out = []
        try:
            async for m in query(prompt=user, options=opts):
                if isinstance(m, AssistantMessage):
                    out += [b.text for b in m.content if isinstance(b, TextBlock)]
            return "".join(out)
        except Exception:
            if attempt == 1:
                raise
    return ""
