from typing import Any

from openai import AsyncOpenAI


class LLMClient:
    """Small async wrapper shared by OpenAI and OpenAI-compatible providers."""

    def __init__(self, api_key: str, base_url: str, model_name: str) -> None:
        self.model_name = model_name
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=2)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model_name, "messages": messages}
        if tools:
            kwargs.update({"tools": tools, "tool_choice": "auto"})
        if response_format:
            kwargs["response_format"] = response_format
        response = await self.client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("llm_returned_no_choices")
        return response.choices[0].message.model_dump(exclude_none=True)
