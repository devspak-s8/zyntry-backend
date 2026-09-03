from __future__ import annotations

import re
from typing import Any


# Some providers historically marked mutating operations as ``risk='low'``.
# Keep the policy safe even when a connector's metadata is incomplete.
WRITE_ACTION_PREFIXES = (
    "create", "update", "delete", "remove", "send", "post", "put", "patch",
    "upload", "invite", "pin", "schedule", "trigger", "merge", "close",
    "cancel", "archive", "revoke", "comment", "commit", "add", "modify",
    "move", "rename", "set", "write",
)


def is_write_action(action: str, definition: Any | None = None) -> bool:
    """Return whether an action mutates an external system."""
    normalized = action.strip().lower()
    if definition is not None:
        if "write" in {str(item).lower() for item in (definition.required_permissions or [])}:
            return True
        if definition.risk in {"medium", "high", "critical"}:
            return True
    return normalized.startswith(WRITE_ACTION_PREFIXES)


def requires_action_confirmation(action: str, definition: Any | None = None) -> bool:
    """All writes require a user confirmation; destructive actions are high risk."""
    return is_write_action(action, definition)


class GuardrailService:
    @staticmethod
    def validate_prompt(prompt: str) -> tuple[bool, str | None]:
        if not prompt or not prompt.strip():
            return False, "Prompt cannot be empty"
        if len(prompt) > 10000:
            return False, "Prompt exceeds maximum length of 10000 characters"
        injection_patterns = [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"ignore\s+the\s+above",
            r"forget\s+(all\s+)?previous\s+instructions",
            r"forget\s+the\s+above",
            r"you\s+are\s+now\s+(a|an)\s+\w+",
            r"pretend\s+you\s+are\s+(a|an)\s+\w+",
            r"act\s+as\s+(a|an)\s+\w+",
            r"roleplay\s+as\s+(a|an)\s+\w+",
            r"simulate\s+being\s+(a|an)\s+\w+",
            r"new\s+instruction[s]?\s*:",
            r"system\s*:\s*you\s+are",
            r"\[system\]|\[user\]|\[assistant\]",
            r"<\|im_start\|>|<\|im_end\|>",
            r"###\s*(instruction|system|prompt)",
            r"override\s+(your|all)\s+(instructions|rules|guidelines)",
            r"disregard\s+(your|all)\s+(instructions|rules|guidelines)",
            r"bypass\s+(your|all)\s+(instructions|rules|guidelines)",
        ]
        for pattern in injection_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return False, "Potentially unsafe prompt detected"
        return True, None

    @staticmethod
    def validate_action_arguments(
        provider: str,
        action: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str | None]:
        suspicious_patterns = [
            r"\.\.\/", r"\.\.\\", r"\$\(.*\)", r"`.*`", r"\|", r";", r"&", r"\${",
        ]
        for key, value in arguments.items():
            if isinstance(value, str):
                for pattern in suspicious_patterns:
                    if re.search(pattern, value):
                        return False, f"Suspicious characters in argument '{key}'"
        return True, None

    @staticmethod
    def sanitize_output(output: Any) -> Any:
        if isinstance(output, str):
            return output.replace("\x00", "")
        if isinstance(output, dict):
            return {k: GuardrailService.sanitize_output(v) for k, v in output.items()}
        if isinstance(output, list):
            return [GuardrailService.sanitize_output(item) for item in output]
        return output
