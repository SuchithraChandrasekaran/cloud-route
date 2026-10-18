"""
Evaluation dataset: a 70-component bank platform.

  * 7 components are DEPLOYED: the bank-easy services running on K3s. Their
    dependencies are exactly what the live cluster reader reports
    (loan-servicing -> account-ledger, credit-scoring; payment-processing ->
    account-ledger). Their cost, 1.31, is the live reader's cost proxy.
  * 63 components are MODELED: the rest of a plausible retail-banking
    platform (databases, message bus, KYC, cards, channels, ...). They are
    NOT deployed. They exist to test the engine on a graph of realistic size
    and depth, and every result that uses them must say so.

Modeled costs use the same proxy as agent/cluster_source.py
(cpu cores * 20 + memory GB * 5). It is a relative size signal, not a bill.
Each component carries a "source" key ("deployed" or "modeled"); the engine
ignores it.
"""


def _cost(cpu: float, mem_gb: float) -> float:
    return round(cpu * 20 + mem_gb * 5, 2)


# (id, dependencies). Cost 1.31 is what the live cluster reader computes.
_DEPLOYED = [
    ("auth", []),
    ("account-ledger", []),
    ("credit-scoring", []),
    ("fraud-detection", []),
    ("notification", []),
    ("loan-servicing", ["account-ledger", "credit-scoring"]),
    ("payment-processing", ["account-ledger"]),
]

# (id, type, cpu cores, memory GB, dependencies)
_MODELED = [
    # --- infrastructure and adapters
    ("core-banking-db", "VM", 4, 16, []),
    ("customer-db", "VM", 2, 8, []),
    ("card-db", "VM", 2, 8, []),
    ("document-store", "VM", 1, 4, []),
    ("message-bus", "VM", 2, 8, []),
    ("secrets-vault", "K8s", 0.5, 1, []),
    ("config-service", "K8s", 0.25, 0.5, []),
    ("log-aggregator", "VM", 1, 4, []),
    ("metrics-store", "VM", 1, 4, []),
    ("hsm-gateway", "VM", 1, 2, []),
    ("sms-gateway-adapter", "K8s", 0.25, 0.25, []),
    ("email-gateway-adapter", "K8s", 0.25, 0.25, []),
    ("credit-bureau-adapter", "K8s", 0.25, 0.5, ["secrets-vault"]),
    ("rate-limiter", "K8s", 0.25, 0.5, ["config-service"]),
    ("waf", "K8s", 0.5, 0.5, ["config-service"]),
    # --- core services
    ("customer-profile", "K8s", 0.5, 1, ["customer-db", "auth"]),
    ("kyc-verification", "K8s", 0.5, 1, ["customer-profile", "document-store"]),
    ("aml-screening", "K8s", 0.5, 1, ["customer-profile", "message-bus"]),
    ("account-opening", "K8s", 0.5, 0.5,
     ["kyc-verification", "account-ledger", "core-banking-db"]),
    ("card-issuing", "K8s", 0.5, 1, ["card-db", "hsm-gateway", "customer-profile"]),
    ("card-authorization", "K8s", 1, 1,
     ["card-issuing", "fraud-detection", "account-ledger"]),
    ("pin-management", "K8s", 0.25, 0.5, ["hsm-gateway", "card-issuing"]),
    ("interest-calculator", "K8s", 0.5, 1, ["account-ledger", "core-banking-db"]),
    ("fee-engine", "K8s", 0.25, 0.5, ["account-ledger", "config-service"]),
    ("statement-generator", "K8s", 0.5, 1,
     ["account-ledger", "document-store", "customer-profile"]),
    ("transaction-history", "K8s", 0.5, 1, ["account-ledger", "message-bus"]),
    ("ledger-reconciliation", "K8s", 0.5, 1,
     ["account-ledger", "core-banking-db", "message-bus"]),
    ("payment-scheduler", "K8s", 0.25, 0.5, ["payment-processing", "message-bus"]),
    ("beneficiary-management", "K8s", 0.25, 0.5, ["customer-profile", "auth"]),
    ("limits-service", "K8s", 0.25, 0.5, ["account-ledger", "config-service"]),
    ("currency-exchange", "K8s", 0.25, 0.5, ["config-service", "message-bus"]),
    ("sms-notifier", "K8s", 0.25, 0.25, ["notification", "sms-gateway-adapter"]),
    ("email-notifier", "K8s", 0.25, 0.25, ["notification", "email-gateway-adapter"]),
    ("push-notifier", "K8s", 0.25, 0.25, ["notification", "message-bus"]),
    # --- domain services
    ("domestic-transfers", "K8s", 0.5, 1,
     ["payment-processing", "limits-service", "beneficiary-management", "fraud-detection"]),
    ("international-transfers", "K8s", 0.5, 1,
     ["payment-processing", "currency-exchange", "aml-screening", "limits-service"]),
    ("standing-orders", "K8s", 0.25, 0.5, ["payment-scheduler", "domestic-transfers"]),
    ("bill-payments", "K8s", 0.5, 0.5, ["payment-processing", "beneficiary-management"]),
    ("instant-payments-rail", "K8s", 1, 1,
     ["payment-processing", "message-bus", "fraud-detection"]),
    ("loan-origination", "K8s", 0.5, 1,
     ["loan-servicing", "kyc-verification", "credit-scoring"]),
    ("loan-underwriting", "K8s", 0.5, 1,
     ["loan-origination", "credit-bureau-adapter", "aml-screening"]),
    ("loan-repayment-scheduler", "K8s", 0.25, 0.5, ["loan-servicing", "payment-scheduler"]),
    ("collections", "K8s", 0.25, 0.5,
     ["loan-repayment-scheduler", "email-notifier", "sms-notifier"]),
    ("mortgage-service", "K8s", 0.5, 1,
     ["loan-servicing", "loan-underwriting", "document-store"]),
    ("fixed-deposit-service", "K8s", 0.25, 0.5, ["account-ledger", "interest-calculator"]),
    ("dispute-management", "K8s", 0.5, 1,
     ["card-authorization", "transaction-history", "document-store"]),
    ("chargeback-processor", "K8s", 0.25, 0.5,
     ["dispute-management", "ledger-reconciliation"]),
    ("regulatory-reporting", "K8s", 0.5, 1,
     ["ledger-reconciliation", "aml-screening", "document-store"]),
    ("audit-trail", "K8s", 0.25, 0.5, ["message-bus", "log-aggregator"]),
    ("data-warehouse-loader", "VM", 2, 8,
     ["core-banking-db", "message-bus", "transaction-history"]),
    ("analytics-dashboard", "K8s", 0.5, 1, ["data-warehouse-loader", "metrics-store"]),
    ("risk-scoring-batch", "VM", 1, 4, ["data-warehouse-loader", "credit-scoring"]),
    ("customer-support-console", "K8s", 0.5, 1,
     ["customer-profile", "transaction-history", "dispute-management"]),
    # --- channels and edge
    ("api-gateway", "K8s", 1, 1, ["auth", "rate-limiter"]),
    ("mobile-banking-api", "K8s", 1, 1,
     ["api-gateway", "transaction-history", "domestic-transfers", "bill-payments",
      "push-notifier"]),
    ("web-banking-bff", "K8s", 0.5, 1,
     ["api-gateway", "statement-generator", "domestic-transfers", "loan-origination"]),
    ("atm-switch", "VM", 1, 2, ["card-authorization", "pin-management", "message-bus"]),
    ("pos-terminal-gateway", "K8s", 0.5, 1, ["card-authorization"]),
    ("branch-teller-app", "K8s", 0.5, 1,
     ["account-opening", "customer-support-console", "api-gateway"]),
    ("open-banking-api", "K8s", 0.5, 1,
     ["api-gateway", "beneficiary-management", "transaction-history"]),
    ("partner-api", "K8s", 0.5, 0.5, ["api-gateway", "loan-origination"]),
    ("public-ingress", "K8s", 0.5, 0.5, ["api-gateway", "waf"]),
    ("admin-portal", "K8s", 0.5, 0.5,
     ["api-gateway", "audit-trail", "customer-support-console"]),
]

EVALUATION_DATASET = [
    {"id": name, "type": "K8s", "daily_cost": 1.31,
     "dependencies": list(deps), "source": "deployed"}
    for name, deps in _DEPLOYED
] + [
    {"id": name, "type": kind, "daily_cost": _cost(cpu, mem),
     "dependencies": list(deps), "source": "modeled"}
    for name, kind, cpu, mem, deps in _MODELED
]
