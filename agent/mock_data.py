"""
Small illustrative migration blueprint used for local development and unit
tests. The full 70-component evaluation dataset (grounded in a real
replatform pattern) lives separately and is what the paper/hackathon
results should be reported against — this file is deliberately small so
engine logic is easy to reason about by hand while developing.
"""

MOCK_MIGRATION_BLUEPRINT = [
    {"id": "Core-Database", "type": "VM", "daily_cost": 450.00, "dependencies": []},
    {"id": "Auth-Service", "type": "K8s", "daily_cost": 45.00, "dependencies": []},
    {"id": "Batch-Processor-1", "type": "VM", "daily_cost": 120.00, "dependencies": ["Core-Database"]},
    {"id": "Batch-Processor-2", "type": "VM", "daily_cost": 25.00, "dependencies": ["Core-Database"]},
    {"id": "API-Gateway", "type": "K8s", "daily_cost": 90.00, "dependencies": ["Auth-Service", "Core-Database"]},
    {"id": "Public-Ingress", "type": "K8s", "daily_cost": 15.00, "dependencies": ["API-Gateway"]},
]
