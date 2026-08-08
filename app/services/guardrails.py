from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError


class JSONSchemaGuardrail:
    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def validate(self, data: Any) -> tuple[bool, str | None]:
        try:
            if self.schema.get("type") == "object":
                parsed = json.loads(data) if isinstance(data, str) else data
                if not isinstance(parsed, dict):
                    return False, "Expected object"
                required = self.schema.get("required", [])
                for field_name in required:
                    if field_name not in parsed:
                        return False, f"Missing required field: {field_name}"
                properties = self.schema.get("properties", {})
                for field_name, field_schema in properties.items():
                    if field_name in parsed:
                        value = parsed[field_name]
                        expected_type = field_schema.get("type")
                        if expected_type == "string" and not isinstance(value, str):
                            return False, f"Field {field_name} must be string"
                        if expected_type == "integer" and not isinstance(value, int):
                            return False, f"Field {field_name} must be integer"
                        if expected_type == "number" and not isinstance(value, (int, float)):
                            return False, f"Field {field_name} must be number"
                        if expected_type == "array" and not isinstance(value, list):
                            return False, f"Field {field_name} must be array"
                        if expected_type == "object" and not isinstance(value, dict):
                            return False, f"Field {field_name} must be object"
                return True, None
            return True, None
        except (json.JSONDecodeError, ValidationError) as exc:
            return False, str(exc)


class MarkdownGuardrail:
    DISALLOWED_PATTERNS = [
        re.compile(r'```(?!.*\n)', re.MULTILINE),
    ]

    @classmethod
    def check(cls, text: str) -> list[str]:
        violations = []
        for pattern in cls.DISALLOWED_PATTERNS:
            if pattern.search(text):
                violations.append("Malformed markdown code block")
        return violations


class TokenGuardrail:
    def __init__(self, max_input_tokens: int = 128000, max_output_tokens: int = 8192) -> None:
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def check_input(self, text: str) -> tuple[bool, str | None]:
        tokens = self.estimate_tokens(text)
        if tokens > self.max_input_tokens:
            return False, f"Input exceeds max tokens: {tokens} > {self.max_input_tokens}"
        return True, None

    def check_output(self, text: str) -> tuple[bool, str | None]:
        tokens = self.estimate_tokens(text)
        if tokens > self.max_output_tokens:
            return False, f"Output exceeds max tokens: {tokens} > {self.max_output_tokens}"
        return True, None


class GuardrailService:
    def __init__(self) -> None:
        self.token_guardrail = TokenGuardrail()
        self.markdown_guardrail = MarkdownGuardrail()

    def validate_input(self, text: str, json_schema: dict[str, Any] | None = None) -> list[str]:
        violations = []
        ok, msg = self.token_guardrail.check_input(text)
        if not ok:
            violations.append(msg)
        if json_schema:
            guard = JSONSchemaGuardrail(json_schema)
            ok, msg = guard.validate(text)
            if not ok:
                violations.append(f"Schema validation failed: {msg}")
        return violations

    def validate_output(self, text: str, json_schema: dict[str, Any] | None = None) -> list[str]:
        violations = []
        ok, msg = self.token_guardrail.check_output(text)
        if not ok:
            violations.append(msg)
        violations.extend(self.markdown_guardrail.check(text))
        if json_schema:
            guard = JSONSchemaGuardrail(json_schema)
            ok, msg = guard.validate(text)
            if not ok:
                violations.append(f"Schema validation failed: {msg}")
        return violations

    def enforce(self, text: str, json_schema: dict[str, Any] | None = None) -> tuple[str, list[str]]:
        violations = self.validate_output(text, json_schema)
        if violations:
            text = f"[GUARDRAIL VIOLATIONS: {', '.join(violations)}]\n\n{text}"
        return text, violations
