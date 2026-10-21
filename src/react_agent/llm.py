"""Call DeepSeek's OpenAI-compatible Tool Calls endpoint."""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import OpenAI, OpenAIError

from react_agent.config import Settings
from react_agent.models import MissingModelConfig, ModelCallError


def wire_messages(messages):
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append({"role": "system", "content": message.content})
        elif isinstance(message, HumanMessage):
            result.append({"role": "user", "content": message.content})
        elif isinstance(message, ToolMessage):
            result.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content})
        elif isinstance(message, AIMessage):
            row = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                row["tool_calls"] = [{"id": t["id"], "type": "function", "function": {
                    "name": t["name"], "arguments": json.dumps(t["args"], ensure_ascii=False)}}
                    for t in message.tool_calls]
            result.append(row)
        else:
            raise TypeError("Unsupported message type")
    return result


class DeepSeekModel:
    mode = "live_deepseek"

    def __init__(self, settings: Settings):
        self.settings = settings

    def invoke(self, messages, tools):
        if not self.settings.api_key:
            raise MissingModelConfig("DEEPSEEK_API_KEY is not configured locally")
        try:
            with OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url,
                        timeout=self.settings.timeout, max_retries=1) as client:
                response = client.chat.completions.create(
                    model=self.settings.model, messages=wire_messages(messages), tools=tools,
                    temperature=0, max_tokens=1400, extra_body={"thinking": {"type": "disabled"}},
                )
        except OpenAIError as exc:
            # Persist the failure category, never request headers or credential-bearing reprs.
            raise ModelCallError(type(exc).__name__) from None
        if not response.choices:
            raise ModelCallError("empty_choices")
        choice = response.choices[0]
        calls = []
        for call in choice.message.tool_calls or []:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                raise ModelCallError("invalid_tool_arguments_json") from None
            if not isinstance(args, dict):
                raise ModelCallError("tool_arguments_must_be_object")
            calls.append({"id": call.id, "name": call.function.name, "args": args, "type": "tool_call"})
        usage = None
        if response.usage:
            usage = {"input_tokens": response.usage.prompt_tokens,
                     "output_tokens": response.usage.completion_tokens,
                     "total_tokens": response.usage.total_tokens}
        return AIMessage(
            content=choice.message.content or "", tool_calls=calls, usage_metadata=usage,
            response_metadata={"model_name": response.model, "finish_reason": choice.finish_reason},
        )
