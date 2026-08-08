from __future__ import annotations

import json
from typing import Any


class ActionPlanner:
    @staticmethod
    def plan(prompt: str, available_actions: list[dict[str, Any]]) -> dict[str, Any]:
        action_descriptions = "\n".join([
            f"- {a['provider']}.{a['name']}: {a.get('description', '')}" for a in available_actions
        ])
        system_prompt = f"""You are an AI assistant that can use tools to help users.
Available actions:
{action_descriptions}

Given a user request, decide if you need to use any actions.
Respond with JSON only:
{{
  "use_tools": true/false,
  "actions": [
    {{
      "provider": "provider_name",
      "action": "action_name",
      "arguments": {{}},
      "confidence": 0.0-1.0,
      "requires_confirmation": true/false
    }}
  ],
  "reasoning": "why these actions"
}}

If no actions are needed, respond with:
{{"use_tools": false, "actions": [], "reasoning": "..."}}"""

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI()
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception:
            return {"use_tools": False, "actions": [], "reasoning": "Planning failed"}
