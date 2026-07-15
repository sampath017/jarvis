"""
Tier 2: Agentic Command Orchestrator

Processes user text commands using resolved physical context.
Emits strict, allow-listed function calls. Never modifies the database directly.

Supports mock mode (pattern-matching) and live mode (OpenRouter API).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from ..config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL_TIER2,
    OPENROUTER_TEMPERATURE,
    USE_MOCK_LLM,
)
from ..models.enums import CRUDEntity, CRUDOperation
from ..models.schemas import (
    FunctionCall,
    Tier2Request,
    Tier2Response,
)
from .function_registry import ALLOWED_FUNCTIONS, FunctionRegistry


class Tier2Orchestrator:
    """
    Tier 2 Agentic Orchestrator.

    Interprets user commands, resolves context, selects permitted functions,
    and emits schema-validated function calls.
    """

    def __init__(
        self,
        function_registry: FunctionRegistry,
        use_mock: bool | None = None,
    ) -> None:
        self.registry = function_registry
        self.use_mock = use_mock if use_mock is not None else USE_MOCK_LLM
        self.api_key = os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)

    def process_command(self, request: Tier2Request) -> Tier2Response:
        """Process a user command and emit function calls."""
        if self.use_mock:
            return self._mock_process(request)
        return self._live_process(request)

    # ── Mock Mode ────────────────────────────────────────────────────────

    def _mock_process(self, request: Tier2Request) -> Tier2Response:
        """Pattern-matching mock for user commands."""
        start = time.perf_counter()

        command = request.user_command.lower()
        place = request.resolved_place or "current location"
        category = request.resolved_place_category or "unknown"
        function_calls: list[FunctionCall] = []
        user_response = ""
        reasoning = ""

        # ── Pattern: Reminder ────────────────────────────────────────
        if any(kw in command for kw in ["remind", "reminder", "remember to"]):
            # Extract what to remember
            text = self._extract_reminder_text(command)
            call = FunctionCall(
                function_name="create_reminder",
                entity=CRUDEntity.REMINDER,
                operation=CRUDOperation.CREATE,
                arguments={
                    "text": text,
                    "trigger_place": place,
                    "trigger_category": category,
                },
            )
            function_calls.append(call)
            user_response = (
                f"I'll remind you to \"{text}\" the next time you're at {place}."
            )
            reasoning = (
                f"Detected reminder intent. Resolved place: {place} ({category}). "
                f"Creating location-triggered reminder."
            )

        # ── Pattern: Note ────────────────────────────────────────────
        elif any(kw in command for kw in ["note", "write down", "save that"]):
            content = self._extract_note_content(command)
            call = FunctionCall(
                function_name="create_note",
                entity=CRUDEntity.NOTE,
                operation=CRUDOperation.CREATE,
                arguments={
                    "content": content,
                    "place": place,
                    "category": category,
                },
            )
            function_calls.append(call)
            user_response = f"Noted: \"{content}\" — saved for {place}."
            reasoning = f"Detected note intent. Content saved with place context."

        # ── Pattern: Task ────────────────────────────────────────────
        elif any(kw in command for kw in ["task", "to do", "todo", "add to list"]):
            title = self._extract_task_title(command)
            call = FunctionCall(
                function_name="create_task",
                entity=CRUDEntity.TASK,
                operation=CRUDOperation.CREATE,
                arguments={
                    "title": title,
                    "context_place": place,
                },
            )
            function_calls.append(call)
            user_response = f"Task added: \"{title}\"."
            reasoning = f"Detected task creation intent."

        # ── Pattern: Save place ──────────────────────────────────────
        elif any(kw in command for kw in ["save this place", "bookmark", "remember this location"]):
            gps = request.context_packet.gps
            lat = gps.latitude if gps else 0.0
            lon = gps.longitude if gps else 0.0
            call = FunctionCall(
                function_name="save_place",
                entity=CRUDEntity.PLACE,
                operation=CRUDOperation.CREATE,
                arguments={
                    "name": place,
                    "latitude": lat,
                    "longitude": lon,
                    "category": category,
                },
            )
            function_calls.append(call)
            user_response = f"Place \"{place}\" has been saved."
            reasoning = f"Detected save-place intent with GPS coordinates."

        # ── Pattern: Automation ──────────────────────────────────────
        elif any(kw in command for kw in ["automate", "when i", "every time"]):
            call = FunctionCall(
                function_name="create_automation",
                entity=CRUDEntity.AUTOMATION,
                operation=CRUDOperation.CREATE,
                arguments={
                    "trigger": f"arrive_at_{place}",
                    "action": command,
                },
            )
            function_calls.append(call)
            user_response = f"Automation created for {place}."
            reasoning = "Detected automation intent."

        # ── Pattern: Unauthorized / malicious function ────────────────
        elif any(kw in command for kw in ["delete all", "drop table", "execute sql"]):
            call = FunctionCall(
                function_name="execute_raw_sql",
                entity=CRUDEntity.EVENT,
                operation=CRUDOperation.DELETE,
                arguments={"query": command},
            )
            function_calls.append(call)
            user_response = "I cannot execute that operation."
            reasoning = "Detected potentially unauthorized operation. Emitting for validation test."

        # ── Fallback ─────────────────────────────────────────────────
        else:
            user_response = "I'm not sure how to handle that command. Could you rephrase?"
            reasoning = "No matching intent pattern found."

        # Validate all function calls through the registry
        for call in function_calls:
            self.registry.validate(call)

        all_valid = all(c.is_valid for c in function_calls) if function_calls else True

        elapsed_ms = (time.perf_counter() - start) * 1000

        return Tier2Response(
            user_response=user_response,
            function_calls=function_calls,
            reasoning=reasoning,
            model_id="mock-tier2-v1",
            tokens_used=0,
            latency_ms=round(elapsed_ms, 2),
            all_calls_valid=all_valid,
        )

    # ── Text extraction helpers ──────────────────────────────────────────

    def _extract_reminder_text(self, command: str) -> str:
        patterns = [
            r"remind me to (.+?)(?:\s+(?:when|next time|the next))",
            r"remind me to (.+)",
            r"remember to (.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".")
        return command

    def _extract_note_content(self, command: str) -> str:
        patterns = [
            r"note that (.+)",
            r"write down(?:\s+that)?\s+(.+)",
            r"save that (.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".")
        return command

    def _extract_task_title(self, command: str) -> str:
        patterns = [
            r"(?:add|create)\s+(?:a\s+)?task[:\s]+(.+)",
            r"to do[:\s]+(.+)",
            r"add to list[:\s]+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                return match.group(1).strip().rstrip(".")
        return command

    # ── Live Mode (OpenRouter) ───────────────────────────────────────────

    def _live_process(self, request: Tier2Request) -> Tier2Response:
        """Call OpenRouter for Tier 2 command processing."""
        import httpx

        start = time.perf_counter()
        prompt = self._build_prompt(request)

        try:
            response = httpx.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENROUTER_MODEL_TIER2,
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": OPENROUTER_MAX_TOKENS,
                    "temperature": OPENROUTER_TEMPERATURE,
                    "response_format": {"type": "json_object"},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            elapsed_ms = (time.perf_counter() - start) * 1000

            parsed = json.loads(content)

            # Parse function calls from response
            function_calls = []
            for fc_data in parsed.get("function_calls", []):
                call = FunctionCall(
                    function_name=fc_data.get("function_name", ""),
                    entity=CRUDEntity(fc_data.get("entity", "EVENT")),
                    operation=CRUDOperation(fc_data.get("operation", "CREATE")),
                    arguments=fc_data.get("arguments", {}),
                )
                self.registry.validate(call)
                function_calls.append(call)

            all_valid = all(c.is_valid for c in function_calls) if function_calls else True

            return Tier2Response(
                user_response=parsed.get("user_response", ""),
                function_calls=function_calls,
                reasoning=parsed.get("reasoning", ""),
                model_id=OPENROUTER_MODEL_TIER2,
                tokens_used=tokens,
                latency_ms=round(elapsed_ms, 2),
                all_calls_valid=all_valid,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return Tier2Response(
                user_response=f"Error processing command: {e}",
                reasoning=f"Tier 2 API error: {e}",
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
      "entity": "string — REMINDER|TASK|NOTE|PLACE|SESSION|PREFERENCE|AUTOMATION|EVENT",
      "operation": "string — CREATE|READ|UPDATE|DELETE|LIST",
      "arguments": {{...}}
    }}
  ],
  "reasoning": "string — brief explanation of your interpretation and decisions"
}}

Rules:
- You may ONLY call functions from the allow-list above.
- You may NOT access databases, run SQL, or call unlisted functions.
- Use the resolved place and context provided.
- Be concise in user_response.
- Always return valid JSON.
"""

    def _build_prompt(self, request: Tier2Request) -> str:
        sections = [f"User Command: \"{request.user_command}\""]

        if request.resolved_place:
            sections.append(f"Current Place: {request.resolved_place} ({request.resolved_place_category})")

        if request.context_packet.gps:
            gps = request.context_packet.gps
            sections.append(f"GPS: {gps.latitude:.4f}, {gps.longitude:.4f}")

        if request.session:
            sections.append(
                f"Active Session: {request.session.status.value}, "
                f"vehicle: {request.session.vehicle_class.value}"
            )

        if request.tier1_response:
            sections.append(f"Tier 1 Resolution: {request.tier1_response.reasoning}")

        return "\n".join(sections)
