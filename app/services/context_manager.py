"""Runtime context budgeting and assembly.

This service decides what can fit in a selected model's working context.  It
does not generate answers; it protects the provider call from context
overflow while preserving the highest-value parts of a request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.model_registry import model_info_for
from app.services.token_engine import TokenEngine


@dataclass(slots=True)
class ContextBudget:
    model_context: int
    reserved_output: int
    safety_margin: int
    working_input: int

    def as_dict(self) -> dict[str, int]:
        return {
            "model_context": self.model_context,
            "reserved_output": self.reserved_output,
            "safety_margin": self.safety_margin,
            "working_input": self.working_input,
        }


@dataclass(slots=True)
class ContextAssembly:
    messages: list[dict[str, str]]
    budget: ContextBudget
    estimated_input_tokens: int
    breakdown: dict[str, int] = field(default_factory=dict)
    dropped_messages: int = 0
    compressed_messages: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def pressure(self) -> float:
        if self.budget.working_input <= 0:
            return 1.0
        return round(min(1.0, self.estimated_input_tokens / self.budget.working_input), 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.as_dict(),
            "estimated_input_tokens": self.estimated_input_tokens,
            "pressure": self.pressure,
            "breakdown": self.breakdown,
            "dropped_messages": self.dropped_messages,
            "compressed_messages": self.compressed_messages,
            "warnings": self.warnings,
        }


class ContextManager:
    """Build a bounded request from runtime, history, knowledge and tools."""

    def __init__(self, *, default_output_tokens: int = 2_048, safety_ratio: float = 0.08) -> None:
        self.default_output_tokens = default_output_tokens
        self.safety_ratio = safety_ratio

    def budget_for(
        self,
        provider: str | None,
        model: str | None,
        *,
        requested_output_tokens: int | None = None,
        context_override: int | None = None,
    ) -> ContextBudget:
        info = model_info_for(provider, model, fallback_context=context_override or 128_000)
        model_context = max(1, context_override or info.max_context)
        output_limit = info.max_output_tokens or self.default_output_tokens
        reserved_output = max(256, min(requested_output_tokens or self.default_output_tokens, output_limit))
        safety_margin = max(256, int(model_context * self.safety_ratio))
        working_input = max(1, model_context - reserved_output - safety_margin)
        return ContextBudget(model_context, reserved_output, safety_margin, working_input)

    def estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        return TokenEngine.estimate_messages(messages)

    def assemble(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str | None,
        model: str | None,
        requested_output_tokens: int | None = None,
        context_override: int | None = None,
    ) -> ContextAssembly:
        budget = self.budget_for(
            provider,
            model,
            requested_output_tokens=requested_output_tokens,
            context_override=context_override,
        )
        normalized = [self._normalize_message(message) for message in messages if message.get("content") is not None]
        selected = list(normalized)
        dropped = 0
        compressed = 0
        warnings: list[str] = []

        # Remove the oldest low-priority messages first.  System messages and
        # the latest user request are never removed during normal trimming.
        while self.estimate_messages(selected) > budget.working_input and len(selected) > 1:
            index = self._oldest_removable_index(selected)
            if index is None:
                break
            selected.pop(index)
            dropped += 1

        # If a single knowledge/tool payload is still too large, keep its
        # beginning and explicitly mark the truncation for the model.
        if self.estimate_messages(selected) > budget.working_input:
            latest_index = len(selected) - 1
            excess = self.estimate_messages(selected) - budget.working_input
            targets = [
                i
                for i, item in enumerate(selected)
                if i != latest_index and item["role"] != "system"
            ]
            if not targets and selected[latest_index]["role"] != "system":
                targets = [latest_index]
            if targets:
                target = targets[0]
                content = selected[target]["content"]
                keep_chars = max(128, len(content) - excess * TokenEngine.CHARS_PER_TOKEN)
                selected[target]["content"] = content[:keep_chars] + "\n[Context truncated to fit the selected model.]"
                compressed += 1
                warnings.append("Context was compressed to fit the selected model.")
            else:
                warnings.append(
                    "System context is larger than the selected model working budget; "
                    "system instructions were preserved."
                )

        # Make one final bounded pass so a provider never receives an
        # unexpectedly large request when there are no removable history
        # messages.  System instructions are deliberately protected: trimming
        # them can silently remove runtime policy, authorization, or safety
        # rules.  If the system context alone is too large, leave it intact and
        # report the overflow so the caller can reject or choose a larger
        # context model rather than sending a malformed policy prompt.
        while self.estimate_messages(selected) > budget.working_input:
            candidates = [
                index
                for index, item in enumerate(selected)
                if item["content"] and item["role"] != "system"
            ]
            if not candidates:
                warnings.append(
                    "System context is larger than the selected model working budget; "
                    "system instructions were preserved."
                )
                break
            target = max(candidates, key=lambda index: len(selected[index]["content"]))
            content = selected[target]["content"]
            excess = self.estimate_messages(selected) - budget.working_input
            remove_chars = min(max(excess * TokenEngine.CHARS_PER_TOKEN, 16), max(1, len(content) - 1))
            marker = "\n[Context truncated.]"
            if len(content) <= remove_chars + len(marker):
                selected[target]["content"] = ""
            else:
                selected[target]["content"] = content[:-remove_chars] + marker
            compressed += 1
            if "Context was compressed to fit the selected model." not in warnings:
                warnings.append("Context was compressed to fit the selected model.")

        estimated = self.estimate_messages(selected)
        breakdown = self._breakdown(selected)
        if estimated > budget.working_input:
            warnings.append("The request still exceeds the model working budget after compression.")
        return ContextAssembly(
            messages=selected,
            budget=budget,
            estimated_input_tokens=estimated,
            breakdown=breakdown,
            dropped_messages=dropped,
            compressed_messages=compressed,
            warnings=warnings,
        )

    @staticmethod
    def _normalize_message(message: dict[str, Any]) -> dict[str, str]:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        # Private bookkeeping keys are not sent to providers.
        return {"role": role, "content": content}

    @staticmethod
    def _oldest_removable_index(messages: list[dict[str, str]]) -> int | None:
        for index, message in enumerate(messages):
            if message["role"] != "system":
                if index == len(messages) - 1:
                    continue
                return index
        return None

    @staticmethod
    def _breakdown(messages: list[dict[str, str]]) -> dict[str, int]:
        breakdown = {"system": 0, "history": 0, "knowledge": 0, "tools": 0, "current_request": 0}
        for index, message in enumerate(messages):
            role = message["role"]
            tokens = TokenEngine.estimate_text(message["content"]) + TokenEngine.MESSAGE_OVERHEAD
            content = message["content"].lower()
            if role == "system":
                key = "system"
            elif index == len(messages) - 1:
                key = "current_request"
            elif "connected internal source context" in content or "retrieved context" in content:
                key = "knowledge"
            elif "tool" in content:
                key = "tools"
            else:
                key = "history"
            breakdown[key] += tokens
        return breakdown
