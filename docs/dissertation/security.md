# Security by Design

## Component Categorization

- **LLMs and external agentic systems**: LLM frontend, AI agents, external AI services
- **Tooling layer**: MCP servers mainly
- **Control system infrastructure**: ArgoCD, GitOps repos, IaC definitions, CI/CD pipelines, operational documentation, etc.
- **Active production environment**: EKS, ALB controller, application, etc.

## Securing the Underlying Infrastructure

- Securing the underlying **control system infrastructure** and **active production environment** itself is the first and obvious step before we even introduce agentic AI into the picture. 
- When pushed, Agentic AI systems can exploit inherent vulnerabilities in the underlying infrastructure to mimic successful operations and could lead to catastrophic failures.
- Lack of accuntability of an agent as opposed to that of a human makes this more critical. 

## Exposing Access to LLMs

## Output and context sanitization.

## 