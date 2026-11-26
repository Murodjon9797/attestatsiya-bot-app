"""Claude API orqali JSON sxemaga mos javob olish (scraper va bot uchun umumiy)."""
from __future__ import annotations

import json
import os

import anthropic

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")


class ClaudeError(RuntimeError):
    pass


async def ask_json(client: anthropic.AsyncAnthropic, *, system: str, content: list[dict] | str,
                   schema: dict, effort: str = "medium", max_tokens: int = 32000) -> dict:
    """So'rov yuboradi va structured outputs orqali sxemaga mos JSON qaytaradi.

    Xavfsizlik filtri so'rovni rad etsa, server tomonidagi `fallbacks="default"`
    so'rovni avtomatik ravishda boshqa modelda qayta bajaradi.
    """
    try:
        async with client.beta.messages.stream(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = await stream.get_final_message()
    except anthropic.RateLimitError as e:
        raise ClaudeError("Claude API limiti oshdi, birozdan so'ng qayta urinib ko'ring.") from e
    except anthropic.AuthenticationError as e:
        raise ClaudeError("ANTHROPIC_API_KEY noto'g'ri yoki ko'rsatilmagan.") from e
    except anthropic.BadRequestError as e:
        raise ClaudeError(f"So'rov xato: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude API xatosi ({e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Claude API bilan aloqa yo'q.") from e

    if msg.stop_reason == "refusal":
        raise ClaudeError("Model so'rovni bajarishdan bosh tortdi.")
    if msg.stop_reason == "max_tokens":
        raise ClaudeError("Javob juda uzun bo'lib ketdi (max_tokens).")
    text = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ClaudeError("Model JSON emas javob qaytardi.") from e
