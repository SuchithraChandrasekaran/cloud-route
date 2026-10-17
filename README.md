# cloud-route

An agent that plans the safe order for moving interdependent services during an
infrastructure migration, explains the plan to the people who have to approve it, and
re-plans when priorities change.

A deterministic graph engine decides every fact: the ordering, the cost estimate and the
rollback scope. An NVIDIA Nemotron model, served through Nebius Token Factory, only explains
and answers questions about those facts. It never decides, never invents, and never applies
a change. It proposes, and a human approves.

Built for the Nebius x NVIDIA Global AI Hackathon (AI apps and agents).
Model: nvidia/nemotron-3-super-120b-a12b.

## The problem

- **Sequencing risk.** Moving components in the wrong order breaks things. Most pre-deployment
  checks look at one change at a time, not at a whole migration plan.
- **Communication risk.** A correct plan is useless if the people who approve it cannot
  follow it. Engineers, PMs and clients each need a different view of the same facts.
- **Cost and blast-radius risk.** Components get double-billed across old and new
  environments for longer than needed, and one failure can trigger an all-or-nothing rollback.

## How it works

1. `agent/cluster_source.py` reads the live K3s cluster and builds a dependency graph.
   Dependencies come from Service selectors and from an explicit annotation,
   `cloud-route/depends-on`, on a Deployment.
2. `agent/engine.py` validates the graph, orders it into safe phases (cheapest-first within a
   phase) and computes a rough overhead heuristic.
3. `agent/orchestrator.py` is a Strands agent. It has one tool, `compute_migration_plan`,
   which returns the phases, the dependencies and the heuristic. That output is the only
   source of facts the model may use. For anything else it says "the tool does not provide
   that".

The agent has four modes:

- **explain**: the plan in plain language for an engineer, PM or client
- **ask**: answers a question using only the tool output (for example, why a service is in
  the last phase)
- **replan**: proposes a parameter change when a priority changes
- **propose-infra**: drafts a new infrastructure request, clearly labeled as a draft

None of them applies anything. Every mode proposes or explains, and a human acts.

## Demo app: bank-easy

A small banking system of seven services (Node/Express, in-memory data), containerized and
deployed to K3s. The agent sequences it as a real system, not synthetic data.

| Service | Port | Depends on |
|---|---|---|
| auth | 4001 | none |
| account-ledger | 4002 | none |
| payment-processing | 4003 | account-ledger |
| credit-scoring | 4004 | none |
| fraud-detection | 4005 | none |
| loan-servicing | 4006 | account-ledger, credit-scoring |
| notification | 4007 | none |

Loan-servicing is the service that breaks if the order is wrong. It cannot approve or pay out
a loan without the ledger and credit scoring.

## Failure demo

    ./demo/failure-demo.sh

Five scenes on the live cluster:

1. The plan cloud-route computes for the cluster.
2. A customer asks for a loan and it succeeds.
3. Credit-scoring is taken down, as if migrated too early, and the same request fails with
   "credit-scoring unreachable".
4. Credit-scoring comes back and loans work again.
5. The agent explains why loan-servicing has to wait for the services it depends on
   (needs `NEBIUS_API_KEY`).

## Steps to run

Prerequisites: Python 3.10+, Node 20, Docker, K3s, and a Nebius Token Factory API key.

    git clone https://github.com/SuchithraChandrasekaran/cloud-route
    cd cloud-route
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python -m pytest tests/ -q

Build the bank-easy images, load them into K3s and deploy:

    cd bank-easy
    for entry in auth-service:auth account-ledger-service:account-ledger payment-processing-service:payment-processing credit-scoring-service:credit-scoring fraud-detection-service:fraud-detection loan-servicing-service:loan-servicing notification-service:notification; do
      docker build -q -t bank-easy/${entry##*:}:v1 ${entry%%:*}
      docker save bank-easy/${entry##*:}:v1 | sudo k3s ctr images import -
    done
    cd ..
    kubectl apply -f k8s/bank-easy.yaml

Plan the migration:

    python -m agent.orchestrator --source k3s
    export NEBIUS_API_KEY=your_key_here
    python -m agent.orchestrator --source k3s --explain engineer
    python -m agent.orchestrator --source k3s --ask "why is loan-servicing in the last phase?"
    python -m agent.orchestrator --source k3s --replan "prioritize downtime over cost"
    python -m agent.orchestrator --source k3s --propose-infra "a staging database connected to monitoring"

Use `--source mock` to run against a small built-in graph without a cluster.

## Status

Working now:

- Deterministic engine, with tests
- Live K3s graph extraction, including the dependency annotation
- All four agent modes against the live cluster
- Seven bank-easy services, containerized and deployed
- The scripted failure demo

Planned, not built yet:

- Full evaluation on a bank-easy-based dataset, plus a large synthetic test set
- Retrieval layer over failure-mode documentation
- Security scan and data-residency flagging
- Cluster resource recommendations
- Persistent storage and a small frontend for bank-easy

## Known issues

Found during live runs and listed in `docs/ISSUES.md`.

Dependency inference is a heuristic. A service that calls another through an environment
variable is only visible to the agent if its Deployment declares the dependency with the
`cloud-route/depends-on` annotation.

## Repo layout

    agent/         engine, cluster reader and the Nemotron agent
    bank-easy/     the seven demo services, each with a Dockerfile
    k8s/           Kubernetes manifests for bank-easy
    demo/          the scripted failure demo
    docs/          known issues
    tests/         unit tests
    daily-logs/    build log


