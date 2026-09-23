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
    raise ValueError(f"unknown backend: {backend}")


async def _ask_claude(system, user, model):
    # 구독 로그인(Claude Code)으로 돈다. system_prompt 를 직접 주면 기본 프롬프트(~2만 토큰)가 빠진다.
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    opts = ClaudeAgentOptions(model=model, system_prompt=system, max_turns=1,
                              allowed_tools=[], setting_sources=[])
    out = []
    async for m in query(prompt=user, options=opts):
        if isinstance(m, AssistantMessage):
            out += [b.text for b in m.content if isinstance(b, TextBlock)]
    return "".join(out)
