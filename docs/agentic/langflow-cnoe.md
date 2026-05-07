# Langflow in the CNOE Stack

Langflow is deployed as a CNOE package alongside Gitea and ArgoCD. It runs at `https://cnoe.localtest.me:8443/langflow` and is protected by Keycloak SSO via oauth2-proxy.

---

## Architecture

```
Browser
  │
  ▼
nginx ingress (cnoe.localtest.me:8443)
  │
  ├─ /langflow/* ──► nginx auth sub-request ──► oauth2-proxy :4180
  │                         │                        │
  │                   authenticated?            Keycloak OIDC
  │                    yes ──────────────────► Langflow :7860
  │                    no  ──────────────────► Keycloak login page
  │
  └─ /oauth2/* ────────────────────────────► oauth2-proxy :4180
                                              (callback, sign-in, sign-out)
```

**Components:**

| Component | What it does | Namespace |
|---|---|---|
| `langflow` Deployment | Langflow 1.5 app server | `langflow` |
| `oauth2-proxy` Deployment | Token validation + Keycloak redirect | `langflow` |
| `keycloak-client-job` | Registers OIDC client in Keycloak on first deploy | `langflow` |
| `langflow-api-keys` Secret | Holds `ANTHROPIC_API_KEY` (user-managed) | `langflow` |
| `langflow-oauth2-proxy` Secret | Holds Keycloak client secret + cookie secret (auto-populated) | `langflow` |
| `langflow-data` PVC | Persistent storage for flows, db, config | `langflow` |

---

## Deployment

### Step 1 — Set the Anthropic API key

```bash
kubectl create secret generic langflow-api-keys \
  -n langflow \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --dry-run=client -o yaml | kubectl apply -f -
```

Do this **once**. The secret persists across cluster rebuilds (as long as the PVC survives).

### Step 2 — Register the ArgoCD Application

Copy the package into the idpbuilder packages directory and let ArgoCD sync it, or apply directly:

```bash
# Option A — let idpbuilder manage it (add to bootstrap)
cp -r control-system-infrastructure/cnoe-stack/packages/langflow \
      ~/.idpbuilder/packages/langflow

# Option B — apply directly to the running cluster
kubectl apply -f control-system-infrastructure/cnoe-stack/packages/langflow/app.yaml
```

ArgoCD will:
1. Create the `langflow` namespace
2. Deploy PVC, RBAC, secrets (placeholder values)
3. Run the `keycloak-client-job` PostSync hook — registers the OIDC client, populates secrets
4. Start Langflow and oauth2-proxy deployments
5. Create the ingress rules

### Step 3 — Verify

```bash
# Check all pods are running
kubectl get pods -n langflow

# Expected:
# NAME                           READY   STATUS    
# langflow-xxxxx                 1/1     Running   
# oauth2-proxy-xxxxx             1/1     Running   
# langflow-keycloak-client-setup-xxxxx   0/1   Completed

# Check the Keycloak client was created
kubectl logs -n langflow job/langflow-keycloak-client-setup

# Check secrets were populated
kubectl get secret langflow-oauth2-proxy -n langflow \
  -o jsonpath='{.data.OAUTH2_PROXY_CLIENT_SECRET}' | base64 -d
```

### Step 4 — Access

Open [https://cnoe.localtest.me:8443/langflow](https://cnoe.localtest.me:8443/langflow)

You will be redirected to the Keycloak login page. Log in with any Keycloak user in the `cnoe` realm (e.g., the `giteaAdmin` user or any user you create in Keycloak Admin).

---

## Importing Flows

Once logged in, import the flows from `agentic/`:

1. **New Flow → Import** → select a `flow.json`
2. The `ANTHROPIC_API_KEY` is already available as an environment variable inside the Langflow pod — you do **not** need to paste it manually into each flow
3. In the `ChatAnthropic` node, leave the API key field empty — Langflow will read it from the environment

---

## Troubleshooting

### oauth2-proxy fails to start

The `OAUTH2_PROXY_CLIENT_SECRET` in the `langflow-oauth2-proxy` secret may still be the placeholder value (`pending-keycloak-job`). Check the job logs:

```bash
kubectl logs -n langflow job/langflow-keycloak-client-setup
```

Common causes:
- Keycloak not ready when the Job ran → delete the Job and let ArgoCD re-create it
- Keycloak admin password secret name differs → check with `kubectl get secrets -n keycloak`
- Keycloak service URL differs from default → edit `KEYCLOAK_URL` in the Job manifest

To force re-run the Job:

```bash
kubectl delete job langflow-keycloak-client-setup -n langflow
# ArgoCD will re-create it on next sync (BeforeHookCreation policy)
kubectl rollout restart deployment/oauth2-proxy -n langflow
```

### Langflow pod stuck in Pending

The PVC may not bind if the storage class doesn't support `ReadWriteOnce`. Check:

```bash
kubectl describe pvc langflow-data -n langflow
kubectl get storageclass
```

### nginx ingress ClusterIP changed

The `hostAliases` in both deployments hardcode the nginx ingress ClusterIP → `cnoe.localtest.me`. If your ClusterIP is different after a cluster rebuild:

```bash
kubectl get svc -n ingress-nginx
```

Update the IP in `deployment.yaml` and `oauth2-proxy.yaml` and re-sync ArgoCD.

---

## Files

```
control-system-infrastructure/cnoe-stack/packages/langflow/
  app.yaml                         ArgoCD Application
  manifests/
    namespace.yaml                 namespace: langflow
    pvc.yaml                       2Gi PVC for Langflow data
    secret.yaml                    langflow-api-keys (user fills) + langflow-oauth2-proxy (Job fills)
    rbac.yaml                      SA + roles for Keycloak Job
    keycloak-client-job.yaml       PostSync Job: register OIDC client, populate secrets
    deployment.yaml                Langflow 1.5 deployment
    oauth2-proxy.yaml              oauth2-proxy deployment
    service.yaml                   ClusterIP services (langflow:7860, oauth2-proxy:4180)
    ingress.yaml                   nginx ingress: /langflow + /oauth2 path rules
```
