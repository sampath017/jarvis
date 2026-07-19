"""
Tier 2: Agentic Command Orchestrator

Processes user text commands using resolved physical context.
Emits strict, allow-listed function calls. Never modifies the database directly.

Uses LangChain ChatOpenAI (via OpenRouter) for automatic LangSmith tracing
and structured Cloud Run logging.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER2,
    OPENROUTER_TEMPERATURE,
)
from ..models.enums import CRUDEntity, CRUDOperation
from ..models.schemas import (
    FunctionCall,
    Tier2Request,
    Tier2Response,
)
from .function_registry import ALLOWED_FUNCTIONS, FunctionRegistry

logger = logging.getLogger(__name__)


class Tier2Orchestrator:
    """
    Tier 2 Agentic Orchestrator.

    Interprets user commands, resolves context, selects permitted functions,
    and emits schema-validated function calls.
    All invocations are automatically traced by LangSmith when enabled.
    """

    def __init__(
        self,
        function_registry: FunctionRegistry,
    ) -> None:
        self.registry = function_registry
        self.llm = ChatOpenAI(
            model=OPENROUTER_MODEL_TIER2,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            max_tokens=OPENROUTER_MAX_TOKENS,
            temperature=OPENROUTER_TEMPERATURE,
            max_retries=3,
            request_timeout=25.0,
            extra_body={
                "provider": {
                    "only": ["DeepInfra", "Together", "Fireworks"],
                    "ignore": ["Novita"],
                    "allow_fallbacks": True,
                },
            },
        )

    def process_command(self, request: Tier2Request) -> Tier2Response:
        """Process a user command and emit function calls via OpenRouter API."""
        start = time.perf_counter()
        prompt = self._build_prompt(request)

        logger.info(
            "Tier 2 invocation started",
            extra={
                "tier": "tier2",
                "phase": "request",
                "user_command": request.user_command,
                "thread_id": request.thread_id,
                "resolved_place": request.resolved_place,
                "prompt": prompt,
                "history_length": len(request.recent_messages),
                "model": OPENROUTER_MODEL_TIER2,
            },
        )

        try:
            # Build message list: system + conversation history + current prompt
            messages = [SystemMessage(content=self._system_prompt())]

            # Include prior conversation history
            if request.recent_messages:
                for m in request.recent_messages:
                    role = m.get("role") or (
                        "user" if m.get("type") in (
                            "human", "user") else "assistant"
                    )
                    content = m.get("content") or ""
                    if role == "user" and content:
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant" and content:
                        messages.append(AIMessage(content=content))

            messages.append(HumanMessage(content=prompt))

            response = self.llm.invoke(messages)
            content = response.content
            elapsed_ms = (time.perf_counter() - start) * 1000

            # Extract token usage from response metadata
            usage = response.usage_metadata or {}
            tokens = usage.get("total_tokens", 0)

            parsed = json.loads(content)

            # Parse function calls from response
            function_calls = []
            for fc_data in parsed.get("function_calls", []):
                call = FunctionCall(
                    function_name=fc_data.get("function_name", ""),
                    entity=CRUDEntity(fc_data.get("entity", "EVENT")),
                    operation=CRUDOperation(
                        fc_data.get("operation", "CREATE")),
                    arguments=fc_data.get("arguments", {}),
                )
                self.registry.validate(call)
                function_calls.append(call)

            all_valid = all(
                c.is_valid for c in function_calls) if function_calls else True

            result = Tier2Response(
                user_response=parsed.get("user_response", ""),
                function_calls=function_calls,
                reasoning=parsed.get("reasoning", ""),
                model_id=OPENROUTER_MODEL_TIER2,
                tokens_used=tokens,
                latency_ms=round(elapsed_ms, 2),
                all_calls_valid=all_valid,
            )

            # Structured logging for observability
            logger.info(
                "Tier 2 invocation completed",
                extra={
                    "tier": "tier2",
                    "phase": "llm_response",
                    "user_command": request.user_command,
                    "thread_id": request.thread_id,
                    "raw_content": content,
                    "user_response": result.user_response,
                    "function_calls": [
                        {
                            "name": fc.function_name,
                            "entity": fc.entity.value,
                            "operation": fc.operation.value,
                            "trigger_category": fc.arguments.get("trigger_category"),
                            "trigger_place": fc.arguments.get("trigger_place"),
                            "is_valid": fc.is_valid,
                            "validation_error": fc.validation_error,
                        }
                        for fc in function_calls
                    ],
                    "reasoning": result.reasoning,
                    "tokens_used": tokens,
                    "latency_ms": round(elapsed_ms, 2),
                    "all_calls_valid": all_valid,
                    "model": OPENROUTER_MODEL_TIER2,
                },
            )

            return result

        except json.JSONDecodeError as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Tier 2 JSON parse error",
                extra={
                    "tier": "tier2",
                    "phase": "error",
                    "user_command": request.user_command,
                    "thread_id": request.thread_id,
                    "error": str(e),
                    "raw_content": content if "content" in dir() else "N/A",
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            return Tier2Response(
                user_response="I had trouble understanding the response. Please try again.",
                reasoning=f"Tier 2 failed to parse LLM response as JSON: {e}",
                model_id=OPENROUTER_MODEL_TIER2,
                latency_ms=round(elapsed_ms, 2),
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Tier 2 invocation failed: %s (%s)",
                e,
                type(e).__name__,
                extra={
                    "tier": "tier2",
                    "phase": "error",
                    "user_command": request.user_command,
                    "thread_id": request.thread_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )
            return Tier2Response(
                user_response="Sorry, I couldn't process that command. Please try again.",
                reasoning=f"Tier 2 failed: {e}",
                model_id=OPENROUTER_MODEL_TIER2,
                latency_ms=round(elapsed_ms, 2),
            )

    def _system_prompt(self) -> str:
        func_specs = json.dumps(
            {name: {"description": spec["description"],
                    "entity": spec["entity"].value,
                    "operation": spec["operation"].value,
                    "required_args": spec["required_args"],
                    "optional_args": spec["optional_args"]}
             for name, spec in ALLOWED_FUNCTIONS.items()},
            indent=2
        )

        return f"""You are Jarvis Tier 2 Agentic Orchestrator. You process user commands using their physical context.

You have access to these allow-listed functions ONLY:
{func_specs}

Return a JSON object with:
{{
  "user_response": "string — concise response to the user",
  "function_calls": [
    {{
      "function_name": "string — must be from the allow-list",
      "entity": "string — TASK|NOTE|PLACE|SESSION|PREFERENCE|AUTOMATION|EVENT",
      "operation": "string — CREATE|READ|UPDATE|DELETE|LIST",
      "arguments": {{...}}
    }}
  ],
  "reasoning": "string — brief explanation of your interpretation and decisions"
}}

Rules:
- You may ONLY call functions from the allow-list above.
- You may NOT access databases, run SQL, or call unlisted functions.
- TASK TRIGGER SPECIFICATION:
  * Activity/Movement Triggers ("when I start walking", "when I start driving/riding", "when I run"):
    Set argument `trigger_category` to "walking", "in_vehicle", or "running".
    Do NOT set `trigger_place` for activity-based triggers (activity triggers must trigger anywhere, regardless of current location).
  * Location/Geofence Triggers ("at home", "when I reach work", "at gym"):
    Set argument `trigger_place` to the target place ("home", "work", "gym").
    Do NOT set `trigger_category` unless both activity and location were requested.
- Use the resolved place and context provided.
- Be concise in user_response.
- Always return valid JSON.
"""

    def _build_prompt(self, request: Tier2Request) -> str:
        sections = [f"User Command: \"{request.user_command}\""]

        if request.resolved_place:
            sections.append(
                f"Current Place: {request.resolved_place} ({request.resolved_place_category})")

        if request.context_packet and request.context_packet.gps:
            gps = request.context_packet.gps
            sections.append(f"GPS: {gps.latitude:.4f}, {gps.longitude:.4f}")

        if getattr(request, "resolved_address", None):
            sections.append(f"Current Address: {request.resolved_address}")

        if request.session:
            sections.append(
                f"Active Session: {request.session.status.value}, "
                f"vehicle: {request.session.vehicle_class.value}"
            )

        if request.tier1_response:
            sections.append(
                f"Tier 1 Resolution: {request.tier1_response.reasoning}")

        return "\n".join(sections)
