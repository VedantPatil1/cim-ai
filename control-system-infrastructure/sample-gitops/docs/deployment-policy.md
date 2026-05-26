# Deployment Policy

This document defines the operational constraints for the `sample-backend`
workload running in the `sample-staging` namespace. All changes to manifests
in this repository must comply with these policies.

## Replica Count

- **Minimum:** 2 replicas at all times for high availability
- **Maximum:** 5 replicas (budget constraint)
- A single-replica deployment is not acceptable in staging or production;
  it creates a single point of failure and is explicitly forbidden.

## Health Probes

- Both `livenessProbe` and `readinessProbe` are **required** on every container.
- Both probes must target `GET /health` on the container port.
- The `/health` endpoint returns `{"status": "ok"}` — probes must not be
  reconfigured to target a different path without a corresponding API change
  that has been reviewed and approved.
- `initialDelaySeconds` must be ≥ 5; `periodSeconds` must be ≥ 10.

## Resource Limits

Every container must declare explicit resource requests and limits:

| Resource | Request | Limit |
|----------|---------|-------|
| CPU      | 100m    | 500m  |
| Memory   | 128Mi   | 256Mi |

Containers without resource limits will be rejected by the admission controller
(Kyverno policy `require-resource-limits`, coming in Phase 2).

## Update Strategy

- Strategy type must be `RollingUpdate`
- `maxUnavailable` must be `0` (zero-downtime deploys)
- `maxSurge` must be `1`
- The `Recreate` strategy causes downtime and is **prohibited**.

## Image Policy

- Images must be pulled from `cnoe.localtest.me:8443` (the internal registry)
- Image tag must be a full 40-character git SHA — the `latest` tag and any
  mutable tags are **prohibited** (immutable image references ensure rollback
  works correctly).

## Namespace

- All workloads for this service run in `sample-staging`.
- Cross-namespace references are not permitted without a platform review.
