"""
The full evaluation dataset (target: ~70 components), grown incrementally
across several work sessions. mock_data.py stays small and separate for
unit tests; this file is what Day 3's real evaluation runs against.

Every component here should be reviewed and adjusted to match your actual
FedEx-style replatform pattern before being treated as "real" — the ones
below are a first draft to react to, not a finished dataset.
"""

EVALUATION_DATASET = [
    # Original 6, from mock_data.py
    {"id": "Core-Database", "type": "VM", "daily_cost": 450.00, "dependencies": []},
    {"id": "Auth-Service", "type": "K8s", "daily_cost": 45.00, "dependencies": []},
    {"id": "Batch-Processor-1", "type": "VM", "daily_cost": 120.00, "dependencies": ["Core-Database"]},
    {"id": "Batch-Processor-2", "type": "VM", "daily_cost": 25.00, "dependencies": ["Core-Database"]},
    {"id": "API-Gateway", "type": "K8s", "daily_cost": 90.00, "dependencies": ["Auth-Service", "Core-Database"]},
    {"id": "Public-Ingress", "type": "K8s", "daily_cost": 15.00, "dependencies": ["API-Gateway"]},

    {"id": "Invoice-Processor", "type": "VM", "daily_cost": 80.00,
     "dependencies": ["Core-Database", "Batch-Processor-2"]},
    {"id": "Report-Generator", "type": "K8s", "daily_cost": 60.00,
     "dependencies": ["Core-Database", "Batch-Processor-1"]},
    {"id": "Billing-Reconciler", "type": "VM", "daily_cost": 55.00,
     "dependencies": ["Invoice-Processor"]},
    {"id": "Shipment-Tracker", "type": "K8s", "daily_cost": 40.00,
     "dependencies": ["API-Gateway"]},
    {"id": "Customer-Notification-Service", "type": "K8s", "daily_cost": 30.00,
     "dependencies": ["API-Gateway", "Auth-Service"]},
    {"id": "Audit-Logger", "type": "K8s", "daily_cost": 20.00,
     "dependencies": ["Core-Database"]},
    {"id": "File-Transfer-Gateway", "type": "VM", "daily_cost": 35.00,
     "dependencies": ["Core-Database"]},
    {"id": "Scheduler-Service", "type": "K8s", "daily_cost": 25.00,
     "dependencies": ["Auth-Service"]},
    {"id": "Archive-Storage", "type": "VM", "daily_cost": 15.00,
     "dependencies": ["File-Transfer-Gateway"]},
    {"id": "Monitoring-Dashboard", "type": "K8s", "daily_cost": 20.00,
     "dependencies": ["API-Gateway", "Public-Ingress"]},
]
