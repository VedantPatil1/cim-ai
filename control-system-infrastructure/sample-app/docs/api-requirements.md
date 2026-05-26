# API Requirements

This document is the authoritative contract for the `sample-backend-api` service.
All pull requests that modify `main.py` or `Dockerfile` must comply with every
requirement listed here.

## Endpoints

### GET /health

- **Response:** HTTP 200, `Content-Type: application/json`
- **Body must be exactly:** `{"status": "ok"}`
- **Constraint:** This exact shape is used by the Kubernetes liveness and readiness
  probes. Any change to the key name or value will cause the pods to fail their
  health checks and be killed/unscheduled.

### GET /items

- **Response:** HTTP 200, paginated JSON object
- **Required body shape:**
  ```json
  {
    "items": [ { "id": int, "name": string, "value": number } ],
    "total": int,
    "page": int,
    "per_page": int
  }
  ```
- **Query parameters:** `page` (default 1) and `per_page` (default 10, max 100)
- **Constraint:** Consumers depend on the `total` field for cursor-based pagination;
  omitting it is a breaking change.

### POST /items

- **Request body:** `{ "name": string, "value": number }`
- **Response:** HTTP 201, returns the created item including its assigned `id`
- **Validation rules:**
  - `name` must be non-empty
  - `value` must be a positive number
- **Error response (400):** `{ "error": "description" }`

### GET /

- **Response:** HTTP 200, `{ "service": string, "version": string }`
- **Constraint:** `version` must match the git tag/SHA used to build the image
  (used by the deployment pipeline to confirm the correct image is running).

## Non-Functional Requirements

- All error responses must use the standard shape: `{ "error": "description" }`
- No endpoint may expose environment variables, secrets, or internal runtime state
- Debug or introspection endpoints are **not permitted** in production builds
- `Content-Type: application/json` on all responses
