"""A small bank-themed graph for --source mock and the unit tests.

It mirrors the deployed bank-easy services, so the mock run tells the same
story as the live cluster. Costs are made-up daily figures, only used to
order components cheapest-first within a phase.
"""

MOCK_MIGRATION_BLUEPRINT = [
    {"id": "notification", "daily_cost": 30, "dependencies": []},
    {"id": "auth", "daily_cost": 45, "dependencies": []},
    {"id": "fraud-detection", "daily_cost": 90, "dependencies": []},
    {"id": "credit-scoring", "daily_cost": 120, "dependencies": []},
    {"id": "account-ledger", "daily_cost": 450, "dependencies": []},
    {"id": "payment-processing", "daily_cost": 200,
     "dependencies": ["account-ledger"]},
    {"id": "loan-servicing", "daily_cost": 260,
     "dependencies": ["account-ledger", "credit-scoring"]},
]
