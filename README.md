# PaySafe — Reliable FinTech Payment System


---

## Project Overview

**PaySafe** is a production-grade FinTech payment system built with Python and FastAPI. It demonstrates core system design concepts applied to real-world payment infrastructure:

- **Double-Entry Ledger** — Every transaction creates balanced DEBIT and CREDIT entries (DEBIT = CREDIT, always), guaranteeing financial consistency.
- **Idempotency** — Clients can safely retry failed requests using an `Idempotency-Key` header; duplicate charges are never created.
- **Transaction Lifecycle Management** — Payments flow through well-defined states: `PENDING → PROCESSING → SUCCESS / FAILED / REFUNDED`.
- **Payment Gateway Abstraction** — A pluggable gateway layer simulates external payment processor integration.
- **Audit Logging** — Every state change is logged for compliance and debugging.
- **REST API** — A fully documented FastAPI application with interactive Swagger UI at `/docs`.

---

## System Architecture

The architecture diagram is included as [`architecture.png`](./architecture.png) in this folder.

Key components:

| Layer | Component | Description |
|-------|-----------|-------------|
| API | `src/api/main.py` | FastAPI app — all REST endpoints |
| Services | `src/services/payment.py` | Orchestrates the full payment lifecycle |
| Services | `src/services/ledger.py` | Double-entry ledger engine |
| Services | `src/services/gateway.py` | External payment gateway abstraction |
| Services | `src/services/idempotency.py` | Duplicate request detection |
| Services | `src/services/audit.py` | Compliance audit logging |
| Core | `src/core/models.py` | Pydantic request/response schemas & enums |
| Core | `src/core/database.py` | SQLite database manager (singleton) |
| Storage | `paysafe.db` | SQLite database (auto-created on first run) |

---

## Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.10+ | Core language |
| FastAPI | REST API framework |
| Uvicorn | ASGI server |
| Pydantic | Data validation & schemas |
| SQLite | Lightweight relational database |
| Pytest | Unit testing |
| Matplotlib | Visualization (architecture diagrams) |
| ReportLab | PDF generation |

---

## Dependencies

Install all dependencies using `pip`:

```bash
pip install -r requirements.txt
```

**`requirements.txt` contents:**
```
fastapi
uvicorn
pydantic
reportlab
matplotlib
requests
pytest
jinja2
```

> **Recommended:** Use a virtual environment to avoid conflicts.

---

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <your-github-repo-url>
cd PaySafe
```

### 2. Create & Activate a Virtual Environment

```bash
# Create
python3 -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Execution Steps

### Run the API Server

```bash
uvicorn src.api.main:app --reload
```

The server starts at **`http://127.0.0.1:8000`**

### Explore the Interactive API Docs

Open your browser and visit:
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

### Example API Calls

**Create a Payment:**
```bash
curl -X POST "http://127.0.0.1:8000/payments" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: unique-key-001" \
  -d '{
    "user_id": "user_101",
    "merchant_id": "merchant_909",
    "amount": 250.00,
    "currency": "USD",
    "payment_method": "CARD",
    "description": "Payment for Order #456"
  }'
```

**Get Payment Details:**
```bash
curl http://127.0.0.1:8000/payments/{transaction_id}
```

**Refund a Payment:**
```bash
curl -X POST "http://127.0.0.1:8000/refunds" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "txn_abc123",
    "reason": "Customer requested refund"
  }'
```

**Check Account Balance:**
```bash
curl http://127.0.0.1:8000/accounts/wallet_user_101/balance
```

**View Ledger Entries:**
```bash
curl http://127.0.0.1:8000/ledger/{transaction_id}
```

**System Health Check:**
```bash
curl http://127.0.0.1:8000/health
```

### Run Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
PaySafe/
├── src/
│   ├── api/
│   │   └── main.py              # FastAPI app & all REST endpoints
│   ├── core/
│   │   ├── models.py            # Pydantic schemas, enums, DTOs
│   │   └── database.py          # SQLite DB manager (singleton)
│   └── services/
│       ├── payment.py           # Payment lifecycle orchestrator
│       ├── ledger.py            # Double-entry ledger engine
│       ├── gateway.py           # Payment gateway abstraction
│       ├── idempotency.py       # Duplicate request prevention
│       └── audit.py             # Compliance audit logger
├── tests/
│   └── test_payment_system.py   # Unit & integration tests
├── architecture.png             # System architecture diagram
├── PaySafe_documentation.pdf    # Full project documentation
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Service info |
| `GET` | `/health` | System health & ledger balance check |
| `POST` | `/payments` | Create a new payment |
| `GET` | `/payments/{id}` | Get payment details + ledger entries |
| `POST` | `/refunds` | Issue a full or partial refund |
| `GET` | `/accounts/{id}/balance` | Get account balance |
| `GET` | `/ledger/{transaction_id}` | Get double-entry ledger records |
| `GET` | `/audit-logs` | Retrieve audit logs |

---

## GitHub Repository

> 🔗 **Repository:** https://github.com/NaazA04/PaySafe

---
