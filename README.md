# cloud-route

A zero-budget build to design, deploy, and operate a self-healing, self-observing cloud
platform on AWS — culminating in an AI co-pilot that doesn't just explain problems, but
proposes, and with explicit human approval, executes fixes.

## What this actually is

1. **A real single-account AWS foundation** — dev/staging/prod separated by naming
   convention and tags, with IAM policies scoping access per environment.
2. **Infrastructure as code** — Terraform modules for VPC, ECS/EKS, security groups, IAM.
3. **A CI/CD pipeline** — GitHub Actions with security scanning (Trivy, Checkov) and a
   manual production approval gate.
4. **Container orchestration** — Docker → ECS Fargate → Kubernetes (Minikube/K3s, with a
   short EKS verification window) with GitOps via ArgoCD.
5. **Observability** — OpenTelemetry, Prometheus, Grafana, CloudWatch alarms.
6. **A governance layer** — a RAID log (Risks, Assumptions, Issues, Dependencies) and an
   environment-readiness tracker, feeding a small executive dashboard.
7. **An AI co-pilot — the centerpiece** — a locally-run LLM (Ollama, free) that:
   - turns raw pipeline and infra events into plain-English RAID entries,
   - answers questions over the RAID log and readiness data via a local RAG index,
   - scores deploy readiness (go / no-go) and is **evaluated** against manual judgment on
     known scenarios — not just built, but measured,
   - **proposes remediation actions** for detected problems (restart a crash-looping pod,
     roll back a bad deploy) drawn from a fixed, pre-approved action list,
   - requires a **human approval gate** before any fix executes — no unattended write access,
   - is proven under **chaos testing**: pods are killed and latency is injected on purpose,
     and the full loop — detect, explain, propose, approve, remediate, recover — is timed
     and documented.

## Why this design

We kept this simple on purpose. No random trendy tech just to sound cool. 
It builds infrastructure that can notice when something's wrong and
suggest a fix, but a real person always has to approve it before anything actually changes

## Zero-budget by design

Everything runs on AWS free tier, a local install, or open-source software. Kubernetes runs
on Minikube/K3s locally; EKS is used only for a short verification window and destroyed
immediately after via `terraform destroy`. The AI co-pilot runs entirely on a local model
(Ollama) — no hosted model API calls. Everything lives in a single AWS account, with
dev/staging/prod separated by naming convention (`migrate-grid-dev-*`, `-staging-*`,
`-prod-*`) and an `Environment` tag on every resource, rather than separate accounts. A
billing alarm is set at $1 from day one as a hard safety net.

## The remediation loop

```
Detect ──► Explain ──► Propose ──► Approve (human) ──► Remediate ──► Recover
```

The AI co-pilot only ever proposes actions from a fixed, reviewed safe-action list. It never
holds standing write access, and every remediation — even in a demo — requires an explicit
human click before it executes. Chaos tests exercise this full loop end to end and the
results (detection time, decision quality, recovery time) are logged, not just described.

## Architecture

```
Synthetic app fleet (10-15 services)
              │
              ▼
   ┌─────────────────────---┐         ┌──────────────────────-┐
   │  Infrastructure layer  │         │   Governance layer    │
   │                        │         │                       │
   │  Terraform, single     │         │  Environment readiness│
   │  AWS account, tag-     │         │  tracker              │
   │  based env separation  │         │  Auto-generated RAID  │
   │  K3s/Minikube + ArgoCD │         │  log                  │
   │  GitOps deploys        │         │  Release gate         │
   │  OpenTelemetry +       │         │  checklist            │
   │  Prometheus + Grafana  │         │                       │
   └──────────┬─────────────┘         └───────────┬───────────┘
              │                                   |
              └───────────────┬───────────────────┘
                               ▼
                     ┌──────────────────-─┐
                     │    AI co-pilot     │
                     │                    │
                     │  Local LLM (Ollama)│
                     │  RAID summarizer   │
                     │  Readiness scorer  │
                     │  (evaluated)       │
                     │  RAG-based Q&A     │
                     │  Remediation       │
                     │  proposals + human │
                     │  approval gate     │
                     └─────────┬──────────┘
                               ▼
                  Executive dashboard
                               │
                               ▼
                  Recruiters & hiring managers
```

## Repo structure

```
.
├── terraform/
│   ├── modules/            # VPC, ECS, EKS, IAM, ECR — reusable across environments
│   └── environments/       # dev, staging, prod-specific configs
├── apps/                   # Synthetic apps used to exercise the platform
│   ├── api-service/
│   ├── queue-worker/
│   └── admin-ui/
├── k8s/                    # Manifests, Ingress, ArgoCD app definitions
├── pipeline/                # GitHub Actions workflows
├── observability/           # Grafana dashboards, Prometheus config, OTel instrumentation
├── governance/               # RAID log schema, readiness tracker, dashboard
├── ai-copilot/               # The centerpiece
│   ├── prompts/              # Summarization and scoring prompts
│   ├── rag/                  # Local vector index over RAID log and runbooks
│   ├── eval/                 # Scoring the AI against manual/human judgment
│   └── remediation/          # Safe-action list, proposal logic, approval gate
├── chaos/
│   ├── scripts/               # Pod-kill and latency-injection scripts
│   └── results/                # Logged detect-to-recover timings
├── docs/
│   ├── adr/                    # One Architecture Decision Record per phase
│   └── architecture.md          # Full system diagram and write-up
├── scripts/
│   └── cleanup.sh                # One-command teardown for anything not free-tier
├── migrate-grid-daily-tasks.csv   # Day-by-day build tracker
├── .gitignore
├── LICENSE
└── README.md
```

## Tech stack

- **Infrastructure**: Terraform, single AWS account with free-tier services (IAM, ECS/ECR), tag-based environment separation, K3s/Minikube, ArgoCD, Docker
- **Observability**: OpenTelemetry, Prometheus, Grafana, CloudWatch (free tier)
- **Governance**: DynamoDB (free tier), dashboard UI
- **AI**: Ollama (Phi-3 / Mistral), FAISS or Chroma for local RAG — no hosted model API calls
- **CI/CD**: GitHub Actions, Trivy, Checkov/TFLint

## Ground rules

- Every AWS resource that isn't explicitly free-tier gets destroyed right after its
  verification window — `terraform destroy` as a one-command habit, not an afterthought.
- A billing alarm is set at $1 in the account from day one.
- The AI co-pilot only ever proposes actions from a fixed, reviewed safe-action list — it
  never gets standing write access, and every remediation requires a human click to execute.
- An ADR is written at the end of every phase, including what didn't work.

## Project plan

**Phase 1 — Infrastructure foundation** (Days 1-30)
Single-account AWS setup with tag-based environment separation, Terraform state backend,
VPC and networking modules, synthetic app containers, ECS deployment, and a full CI/CD
pipeline with security scanning.

**Phase 2 — Kubernetes and GitOps** (Days 31-45)
Local K3s/Minikube cluster, Kubernetes manifests, ArgoCD GitOps sync, ingress routing, and a
scheduled drift-detection check.

**Phase 3 — Observability** (Days 46-55)
OpenTelemetry instrumentation, Prometheus and Grafana dashboards, centralized logging, and
alerting through CloudWatch.

**Phase 4 — Governance layer** (Days 56-71)
RAID log schema and storage, environment readiness tracker, release gate checklist logic,
and a dashboard tying it all together.

**Phase 5 — AI co-pilot and release** (Days 72-90)
Local LLM setup, event summarization, an evaluated readiness scorer, local RAG-based Q&A,
remediation proposals with a human approval gate, chaos testing with logged recovery
numbers, and final documentation and publishing.


## Architecture Decision Records

- [ ] ADR 01: CI/CD pipeline design
- [ ] ADR 02: GitOps over imperative deploys
- [ ] ADR 03: Observability stack choices
- [ ] ADR 04: Governance data model
- [ ] ADR 05: AI co-pilot design — why local, why a fixed action list, why a human gate

## Chaos testing results

Detect-to-recover timings for the full remediation loop, logged honestly once tests are run.

