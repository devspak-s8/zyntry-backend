"""Small, non-semantic helpers for parsing model JSON responses.

Model providers occasionally return a JSON object wrapped in markdown or with
an omitted comma/trailing comma. These helpers only repair unambiguous JSON
syntax; they never infer or alter field values. Callers still validate the
resulting object against their Pydantic schema.
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(content: str) -> dict[str, Any]:
    """Extract and safely parse one JSON object from provider output."""

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model response did not contain a JSON object")
    json_object = cleaned[start : end + 1]
    try:
        value = json.loads(json_object)
    except json.JSONDecodeError:
        value = repair_json_object(json_object)
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def repair_json_object(value: str) -> dict[str, Any]:
    """Repair only unambiguous separators and trailing commas."""

    candidate = value
    for _ in range(12):
        try:
            parsed = json.loads(candidate)
            if not isinstance(parsed, dict):
                raise ValueError("Model response must be a JSON object")
            return parsed
        except json.JSONDecodeError as exc:
            position = exc.pos
            current_index = position
            while current_index < len(candidate) and candidate[current_index].isspace():
                current_index += 1
            previous_index = position - 1
            while previous_index >= 0 and candidate[previous_index].isspace():
                previous_index -= 1
            current = candidate[current_index] if current_index < len(candidate) else ""
            previous = candidate[previous_index] if previous_index >= 0 else ""

            if "trailing comma" in exc.msg.lower():
                comma_index = candidate.rfind(",", 0, position + 1)
                if comma_index >= 0:
                    after_comma = comma_index + 1
                    while after_comma < len(candidate) and candidate[after_comma].isspace():
                        after_comma += 1
                    if after_comma < len(candidate) and candidate[after_comma] in "}]":
                        candidate = candidate[:comma_index] + candidate[comma_index + 1 :]
                        continue
            if (
                exc.msg == "Expecting ',' delimiter"
                and current in '\"{[tfn-0123456789'
                and previous in '\"}]el0123456789'
            ):
                candidate = candidate[:current_index] + "," + candidate[current_index:]
                continue
            if current in "}]" and previous == "," and (
                exc.msg in {
                    "Expecting property name enclosed in double quotes",
                    "Expecting value",
                }
                or "trailing comma" in exc.msg.lower()
            ):
                candidate = candidate[:previous_index] + candidate[previous_index + 1 :]
                continue
            if exc.msg == "Expecting ':' delimiter" and current in '\"{[tfn-0123456789':
                candidate = candidate[:current_index] + ":" + candidate[current_index:]
                continue
            raise
    raise ValueError("Model response JSON could not be repaired safely")
