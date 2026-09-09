"""
Tier 2: Agentic Command Orchestrator

Processes user text commands using resolved physical context.
Emits strict, allow-listed function calls. Never modifies the database directly.

Uses LangChain ChatOpenAI with native structured output (.with_structured_output)
via OpenRouter for LangGraph workflow execution, LangSmith tracing, and schema validation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

from ..models.enums import CRUDEntity, CRUDOperation
from ..models.schemas import FunctionCall, Tier2Request, Tier2Response
from ..settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER2,
    OPENROUTER_TEMPERATURE,
)
from .function_registry import ALLOWED_FUNCTIONS, FunctionRegistry

logger = logging.getLogger(__name__)


class FunctionCallItem(BaseModel):
    """Schema for an individual function call emitted by Tier 2."""

    function_name: str = Field(
        ...,
        description="Name of the function to execute (e.g. create_task, get_tasks, create_place, etc.)",
    )
    entity: CRUDEntity = Field(
        default=CRUDEntity.EVENT,
        description="Entity targeted by the function: TASK, NOTE, PLACE, PREFERENCE, REMINDER, EVENT, NOTIFICATION, CONTEXT_RULE",
    )
    operation: CRUDOperation = Field(
        default=CRUDOperation.CREATE,
        description="Operation to perform: CREATE, READ, UPDATE, DELETE, SEARCH, LIST, UPSERT",
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Dictionary of keyword arguments required by the function",
    )

    @field_validator("entity", mode="before")
    @classmethod
    def normalize_entity(cls, v: Any) -> CRUDEntity:
        """Coerce strings to CRUDEntity enum case-insensitively."""
        if isinstance(v, CRUDEntity):
            return v
        if isinstance(v, str):
            normalized = v.strip().upper()
            try:
                return CRUDEntity(normalized)
            except ValueError:
                return CRUDEntity.EVENT
        return CRUDEntity.EVENT

    @field_validator("operation", mode="before")
    @classmethod
    def normalize_operation(cls, v: Any) -> CRUDOperation:
        """Coerce strings to CRUDOperation enum case-insensitively."""
        if isinstance(v, CRUDOperation):
            return v
        if isinstance(v, str):
            normalized = v.strip().upper()
            try:
                return CRUDOperation(normalized)
            except ValueError:
                return CRUDOperation.CREATE
        return CRUDOperation.CREATE

    @field_validator("arguments", mode="before")
    @classmethod
    def normalize_arguments(cls, v: Any) -> dict[str, Any]:
        """Ensure arguments is a dict, decoding if passed as string."""
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return {}


class Tier2StructuredOutput(BaseModel):
    """Schema for Tier 2 structured output."""

    user_response: str = Field(
        default="",
        description="Helpful, conversational message back to the user.",
    )
    function_calls: list[FunctionCallItem] = Field(
        default_factory=list,
        description="List of structured function calls to perform allowed CRUD actions.",
    )
    reasoning: str = Field(
        default="",
        description="Internal reasoning regarding user intent, context, and selected tools.",
    )


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
                    "allow_fallbacks": True,
                },
            },
        )
        self.structured_llm = self.llm.with_structured_output(Tier2StructuredOutput)

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
                        "user" if m.get("type") in ("human", "user") else "assistant"
                    )
                    content = m.get("content") or ""
                    if role == "user" and content:
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant" and content:
                        messages.append(AIMessage(content=content))

            # Current user command and context prompt
            messages.append(HumanMessage(content=prompt))

            # Models like glm, rwkv, deepseek-r1 don't support OpenAI structured output / json_schema on OpenRouter
            # Bypassing doomed 400 calls saves 2.5-3.5 seconds on every single request
            model_lower = OPENROUTER_MODEL_TIER2.lower()
            supports_tool_calling = not any(k in model_lower for k in ["glm", "rwkv", "deepseek-r1"])

            parsed_raw = None
            if supports_tool_calling:
                try:
                    parsed_raw = self.structured_llm.invoke(messages)
                except Exception as parse_err:
                    logger.warning(
                        "⚠️ [TIER2_PARSE_FALLBACK] Structured output parsing error: %s. Attempting direct parse...",
                        parse_err,
                    )

            if parsed_raw is None:
                raw_ai_msg = self.llm.invoke(messages)
                content_str = (
                    raw_ai_msg.content
                    if isinstance(raw_ai_msg.content, str)
                    else str(raw_ai_msg.content)
                )
                import re
                json_match = re.search(r"\{[\s\S]*\}", content_str)
                if json_match:
                    try:
                        parsed_raw = json.loads(json_match.group(0))
                    except Exception:
                        parsed_raw = {
                            "user_response": content_str,
                            "function_calls": [],
                            "reasoning": "Fallback raw text",
                        }
                else:
                    parsed_raw = {
                        "user_response": content_str,
                        "function_calls": [],
                        "reasoning": "Fallback raw text",
                    }

            if isinstance(parsed_raw, Tier2StructuredOutput):
                parsed = parsed_raw
            elif isinstance(parsed_raw, dict):
                parsed = Tier2StructuredOutput.model_validate(parsed_raw)
            else:
                parsed = Tier2StructuredOutput.model_validate(getattr(parsed_raw, "__dict__", {}))

            elapsed_ms = (time.perf_counter() - start) * 1000

            # Convert to internal FunctionCall instances, auto-filling known schema entity/operation
            function_calls = []
            for fc_item in parsed.function_calls:
                entity = fc_item.entity
                operation = fc_item.operation

                # Auto-align with registry if function is recognized
                if fc_item.function_name in ALLOWED_FUNCTIONS:
                    spec = ALLOWED_FUNCTIONS[fc_item.function_name]
                    entity = spec["entity"]
                    operation = spec["operation"]

                call = FunctionCall(
                    function_name=fc_item.function_name,
                    entity=entity,
                    operation=operation,
                    arguments=fc_item.arguments,
                )
                self.registry.validate(call)
                function_calls.append(call)

            all_valid = all(
                c.is_valid for c in function_calls) if function_calls else True

            result = Tier2Response(
                user_response=parsed.user_response,
                function_calls=function_calls,
                reasoning=parsed.reasoning,
                model_id=OPENROUTER_MODEL_TIER2,
                tokens_used=0,
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
                    "latency_ms": round(elapsed_ms, 2),
                    "all_calls_valid": all_valid,
                    "model": OPENROUTER_MODEL_TIER2,
                },
            )

            return result

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.critical(
                "Tier 2 invocation failed: %s (%s)",
                e,
                type(e).__name__,
                exc_info=True,
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

Output Format:
You MUST format your entire response as a single valid JSON markdown block:
```json
{{
  "user_response": "<A concise, friendly response to the user.>",
  "function_calls": [
    {{
      "function_name": "<Name of allow-listed function>",
      "entity": "TASK" | "NOTE" | "PLACE" | "PREFERENCE" | "REMINDER" | "EVENT" | "NOTIFICATION" | "CONTEXT_RULE",
      "operation": "CREATE" | "READ" | "UPDATE" | "DELETE" | "SEARCH" | "LIST" | "UPSERT",
      "arguments": {{ "<arg_name>": "<arg_value>" }}
    }}
  ],
  "reasoning": "<1-2 sentences reasoning regarding intent and context.>"
}}
```
Do NOT include any extra conversation or explanation outside the JSON code block.

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
- For a follow-up such as "change my workout reminder", prefer
  `update_reminder_by_title` or `update_note_by_title`; the caller will not
  know internal database IDs.
- Context rules use `trigger_type` of `GEOFENCE_ENTER`, `ACTIVITY_ENTER`, or
  `TIME_AFTER`. Their `trigger` and `action` arguments are JSON objects.
  Supported actions are `NOTIFY` (`title`, `body`), `APPEND_NOTE` (`note_id`
  or `note_title`, `text`), and `UPDATE_REMINDER` (`reminder_id` or
  `reminder_title`, `patch`).
- CONVERSATIONAL & QUERY RESOLUTION:
  * When the user asks about their active reminders, notes, tasks, or riding state (e.g. "do we have any reminders", "what notes do I have", "show my reminders"):
    Inspect the provided context sections directly and answer the user completely in `user_response`.
    Do NOT output intermediate promises like "Let me check..." or "Checking..." — always provide the final, complete answer in `user_response` directly.
    You do NOT need to call `list_reminders` or `list_notes` when the records are already in your prompt context.
- Keep user_response brief, direct, and conversational (1-2 sentences max).
- Keep reasoning succinct (1-2 sentences). Never produce runaway text.
"""

    def _build_prompt(self, request: Tier2Request) -> str:
        sections = [f"User Command: \"{request.user_command}\""]

        if request.user_reminders:
            rem_items = []
            for r in request.user_reminders[:10]:
                title = r.get("title") or r.get("body", "Reminder")
                loc = f" at {r.get('location_name')}" if r.get("location_name") else ""
                act = f" on {r.get('activity')}" if r.get("activity") else ""
                rem_items.append(f"- {title}{loc}{act} [{r.get('status', 'ACTIVE')}]")
            sections.append("User's Active Reminders:\n" + "\n".join(rem_items))
        else:
            sections.append("User's Active Reminders: None")

        if request.user_notes:
            note_items = [f"- {n.get('text', '')}" for n in request.user_notes[:8]]
            sections.append("User's Recent Notes:\n" + "\n".join(note_items))

        if request.user_tasks:
            task_items = [f"- {t.get('title', '')} (Status: {t.get('status', 'PENDING')})" for t in request.user_tasks[:8]]
            sections.append("User's Tasks:\n" + "\n".join(task_items))

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
