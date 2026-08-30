# Authorized staging security tests

The `Authorized staging security tests` workflow is manual and targets only a
GitHub `staging` environment. It does not run against production.

Configure these secrets on the staging environment before dispatching it:

- `STAGING_BASE_URL`: HTTPS staging API URL (for example,
  `https://staging-api.example.test`)
- `STAGING_ZAP_TOKEN`: disposable staging bearer token used only by ZAP
- `STAGING_TENANT_A_SESSION` and `STAGING_TENANT_B_SESSION`: disposable
  `zyntra_session` cookie values for two different staging tenants
- `STAGING_TENANT_A_PROJECT_ID` and `STAGING_TENANT_B_PROJECT_ID`
- `STAGING_TENANT_A_RUNTIME_ID` and `STAGING_TENANT_B_RUNTIME_ID`

The tenant check is read-only. Each session must be able to read its own
project/runtime, while the other session must receive HTTP 403 or 404 for those
identifiers. Rotate and revoke the disposable sessions after the run.

The deploy workflow scans the exact SHA-tagged GHCR image with Trivy before any
deployment job can run. High and critical fixed vulnerabilities fail the
deployment and the report is uploaded as a workflow artifact.
