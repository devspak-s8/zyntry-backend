import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.invoke.router import _is_runtime_ready


@pytest.mark.parametrize(
    ("status_value", "expected"),
    [
        ("active", True),
        ("ACTIVE", True),
        (" queued ", True),
        ("validating", True),
        ("failed", False),
        ("cancelled", False),
        (None, True),
    ],
)
def test_runtime_readiness_accepts_operational_states(status_value, expected):
    assert _is_runtime_ready(status_value) is expected
