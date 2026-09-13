"""Small text-completion helper on top of the LLM configured in provider settings."""

import json

from ..logger import logger


def _split_model(model: str) -> tuple[str, str]:
    provider, _, name = model.partition("/")
    return (provider.lower(), name) if name else ("anthropic", provider)


async def ask(providers: dict[str, str], prompt: str, system: str | None = None, max_tokens: int = 4000) -> str:
    """Return the model's text reply. Uses the provider/model from Settings > Auto-Fetch."""
    provider, model = _split_model(providers.get("llm_model") or "anthropic/claude-sonnet-5")
    api_key = providers.get("llm_api_key")
    if not api_key:
        raise RuntimeError("Missing provider settings: llm_api_key. Configure it in Settings > Providers.")

    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "You are a precise assistant. Answer with exactly what is asked.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    if provider == "openai":
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": ([{"role": "system", "content": system}] if system else [])
                    + [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    raise RuntimeError(f"LLM provider '{provider}' is not supported for text tasks (use anthropic/… or openai/…)")


async def ask_json(providers: dict[str, str], prompt: str, system: str | None = None) -> dict | list:
    """Ask for JSON only and parse it, tolerating code fences."""
    raw = (await ask(providers, prompt, system)).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"LLM returned non-JSON: {raw[:300]}")
        raise RuntimeError("The LLM did not return valid JSON")
