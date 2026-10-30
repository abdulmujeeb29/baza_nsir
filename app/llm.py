"""One small interface over several LLM providers: chat_with_tools(messages, tools) -> LLMResponse.

Messages use the OpenAI chat format (system, user, assistant with tool_calls, tool).
Tools are plain dicts: {name, description, parameters (JSON schema)}.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
REQUEST_TIMEOUT = 40


class LLMError(Exception):
    """Raised for provider failures. The message is safe to show to users."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list = field(default_factory=list)


def config():
    return {
        "provider": (os.getenv("LLM_PROVIDER") or "").strip().casefold(),
        "model": (os.getenv("LLM_MODEL") or "").strip(),
        "api_key": (os.getenv("LLM_API_KEY") or "").strip(),
        "base_url": (os.getenv("LLM_BASE_URL") or "").strip(),
    }


class OpenAICompatibleLLM:
    """OpenAI, Azure OpenAI (v1 endpoint) and Gemini (OpenAI-compatible endpoint)."""

    def __init__(self, model, api_key, base_url=None):
        from openai import OpenAI
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=REQUEST_TIMEOUT, max_retries=1)

    def chat_with_tools(self, messages, tools):
        import openai
        payload = [{"type": "function", "function": t} for t in tools]
        try:
            response = self.client.chat.completions.create(model=self.model, messages=messages,
                                                           tools=payload or openai.NOT_GIVEN)
        except openai.APITimeoutError as error:
            raise LLMError("The language model took too long to respond.") from error
        except (openai.AuthenticationError, openai.PermissionDeniedError) as error:
            raise LLMError("The language model rejected the API key.") from error
        except openai.RateLimitError as error:
            raise LLMError("The language model is busy or out of quota. Please try again in a minute.") from error
        except openai.APIError as error:
            raise LLMError("The language model service returned an error.") from error
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": call.function.arguments}
            calls.append(ToolCall(call.id, call.function.name, arguments))
        return LLMResponse(message.content or "", calls)


class AnthropicLLM:
    def __init__(self, model, api_key):
        import anthropic
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT, max_retries=1)

    def chat_with_tools(self, messages, tools):
        import anthropic
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        converted = []
        for m in messages:
            if m["role"] == "system":
                continue
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                    converted[-1]["content"].append(block)
                else:
                    converted.append({"role": "user", "content": [block]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                for call in m["tool_calls"]:
                    content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                                    "input": json.loads(call["function"]["arguments"] or "{}")})
                converted.append({"role": "assistant", "content": content})
            else:
                converted.append({"role": m["role"], "content": m["content"]})
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=2048, system=system, messages=converted,
                tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools])
        except anthropic.APITimeoutError as error:
            raise LLMError("The language model took too long to respond.") from error
        except anthropic.AuthenticationError as error:
            raise LLMError("The language model rejected the API key.") from error
        except anthropic.RateLimitError as error:
            raise LLMError("The language model is busy or out of quota. Please try again in a minute.") from error
        except anthropic.APIError as error:
            raise LLMError("The language model service returned an error.") from error
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"]
        return LLMResponse(text, calls)


class FakeLLM:
    """Replays scripted responses for tests. Each script item is an LLMResponse or an Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.model = "fake"

    def chat_with_tools(self, messages, tools):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": [t["name"] for t in tools]})
        if not self.script:
            return LLMResponse("I could not finish this answer.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def get_llm():
    settings = config()
    provider, model, key = settings["provider"], settings["model"], settings["api_key"]
    if not key:
        raise LLMError("No language model API key is configured on the server.")
    if provider in {"openai", "azure"}:
        if provider == "azure" and not settings["base_url"]:
            raise LLMError("LLM_BASE_URL is required for the azure provider.")
        return OpenAICompatibleLLM(model, key, settings["base_url"] or None)
    if provider == "gemini":
        return OpenAICompatibleLLM(model or "gemini-2.5-flash", key, settings["base_url"] or GEMINI_OPENAI_URL)
    if provider == "anthropic":
        return AnthropicLLM(model, key)
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'. Use azure, openai, gemini or anthropic.")


def model_name():
    settings = config()
    return f"{settings['provider'] or 'none'}:{settings['model'] or 'none'}"


def ping():
    response = get_llm().chat_with_tools([{"role": "user", "content": "Reply with the single word: ready"}], [])
    return response.text.strip()[:50]
