# Feature rollouts

Feature flags are managed through the admin feature-flag endpoints and evaluated on the server.
The `enabled` field is the global kill switch.

## Target selected beta testers

Allowlist entries use an explicit target type:

```json
[
  "user:00000000-0000-0000-0000-000000000000",
  "org:00000000-0000-0000-0000-000000000000",
  "email:beta@example.com"
]
```

For an allowlist-only beta, set `enabled` to `true`, `default_value` to `false`, and
`rollout_percentage` to `0`.

```json
{
  "key": "runtime_assistant_v2",
  "name": "Runtime Assistant v2",
  "scope": "runtime",
  "flag_type": "percentage",
  "enabled": true,
  "default_value": false,
  "rollout_percentage": 0,
  "allowlist": ["email:beta@example.com"]
}
```

## Gradual rollout

Increase `rollout_percentage` through controlled stages such as 5, 10, 25, 50, and 100.
Assignment is deterministic and uses the organization ID when available, keeping everyone in an
organization in the same cohort.

## Backend enforcement

Backend routes must enforce a flag; hiding a frontend control is not sufficient.

```python
from typing import Annotated

from fastapi import Depends

from app.api.v1.features.dependencies import require_feature


@router.post("/v2")
async def use_v2(
    _: Annotated[None, Depends(require_feature("runtime_assistant_v2"))],
):
    ...
```

Authenticated clients can retrieve their evaluated flags from `GET /api/v1/features/me`. The
response contains only flag keys and boolean values; targeting rules remain private.
