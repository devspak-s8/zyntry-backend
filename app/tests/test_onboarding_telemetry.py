from __future__ import annotations

import uuid

from app.services.onboarding.telemetry import OnboardingTraceSink, use_call, use_trace


class _Session:
    def __init__(self) -> None:
        self.new: list[object] = []

    def add(self, value: object) -> None:
        self.new.append(value)


def test_onboarding_trace_stores_usage_metadata_without_prompt_content() -> None:
    session = _Session()
    sink = OnboardingTraceSink(session=session, user_id=uuid.uuid4(), session_id=None)
    prompt = "customer private prompt that must not be persisted"
    call_id = sink.start_call(
        operation="conversation_response",
        model="gemini-2.5-flash",
        messages=[{"role": "user", "content": prompt}],
    )

    with use_trace(sink), use_call(call_id):
        assert sink is not None
    sink.finish_call(
        call_id,
        status="completed",
        provider="google",
        usage={"prompt_tokens": 12, "completion_tokens": 4},
        output_text="safe response",
    )

    event = session.new[0]
    assert event.input_tokens == 12
    assert event.output_tokens == 4
    assert event.total_tokens == 16
    assert event.provider == "google"
    assert prompt not in str(event.metadata_)
