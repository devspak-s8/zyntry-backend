from __future__ import annotations

import pytest

from scripts.setup_beta_cohort import COHORT_KEY, normalize_emails


def test_beta_cohort_email_normalization_is_idempotent() -> None:
    emails = normalize_emails([" Beta@Example.com ", "beta@example.com", "SECOND@example.com"])

    assert emails == ["beta@example.com", "second@example.com"]
    assert COHORT_KEY == "founding_beta_2026_08"


def test_beta_cohort_rejects_invalid_email() -> None:
    with pytest.raises(ValueError):
        normalize_emails(["not-an-email"])
