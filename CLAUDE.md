# CLAUDE.md — hdfc-statement-loader

Onboarding guide for AI assistants. Read this at the start of every session.

---

## Project Overview

A production financial pipeline that polls HDFC Bank transaction alert emails daily via the Gmail API, parses 4 email formats (UPI debit old/new, UPI credit, netbanking, debit card), stores parsed transactions in a Neon PostgreSQL database, classifies them into spend categories using a rules → memory → hierarchical LightGBM fallback pipeline, and sends a nightly summary email. A web-based batch review UI (`/review`) is served from the same Cloud Run service, replacing the previous manual SQL workflow for reviewing and approving categorized transactions. The system runs on Google Cloud Run, is triggered daily at 9 PM IST by Cloud Scheduler, and deploys automatically via GitHub Actions on every push to `main`.

---

## Directory Structure

```
hdfc-statement-loader/
├── loader/                         # Gmail polling + email parsing pipeline
│   ├── app.py                      # ENTRY POINT: Flask app, Cloud Run trigger, review blueprint
│   ├── gmail_poller.py             # Gmail polling logic + email parsing (CLI runner)
│   ├── review.py                   # Flask Blueprint: batch review API (7 routes)
│   ├── parser.py                   # Email format detection & field extraction
│   ├── db.py                       # PostgreSQL schema creation & queries
│   ├── auth.py                     # One-time OAuth2 setup (run manually once)
│   ├── generate_inserts.py         # Excel → SQL migration utility
│   ├── load_excel.py               # Data feed loading utility
│   └── seed_test_batch.py          # One-shot: inserts a test pending batch for UI testing
│
├── templates/
│   └── review.html                 # Batch review UI (vanilla HTML/CSS/JS)
│
├── categorizer/                    # Transaction classification pipeline
│   ├── main.py                     # Full training pipeline (run to retrain model)
│   ├── batch_process.py            # ENTRY POINT: batch classification CLI
│   ├── requirements.txt            # Categorizer-specific dependencies
│   ├── config/
│   │   └── rules.json              # Keyword → category mapping rules
│   ├── ingestion/
│   │   ├── database.py             # DB connection & schema queries
│   │   ├── transactions.py         # Batch creation & completion logic
│   │   └── parser.py               # (Minimal use)
│   ├── models/
│   │   ├── train.py                # Hierarchical LightGBM trainer (3-stage)
│   │   ├── predict.py              # 3-stage inference (type → category → subcategory)
│   │   └── registry.py             # GCS joblib model store (save/load champion bundle)
│   ├── processing/
│   │   ├── pipeline.py             # Main prediction orchestration
│   │   ├── cleaner.py              # Text normalization
│   │   ├── rules.py                # Rule-based prediction layer
│   │   ├── memory.py               # Merchant-level prediction cache
│   │   └── merchant.py             # Merchant name extraction
│   ├── evaluation/
│   │   └── metrics.py              # Evaluation metrics
│
├── tests/
│   ├── conftest.py                 # Adds loader/ to sys.path for imports
│   ├── test_parser.py              # 40+ unit tests for email parsing
│   ├── test_gmail_poller.py        # Integration tests (mocked)
│   ├── test_generate_inserts.py    # Migration tool tests
│   └── test_review.py              # Token auth + /api/categories shape tests
│
├── .github/
│   └── workflows/
│       └── deploy.yml              # GitHub Actions: test → build → deploy to Cloud Run
│
├── requirements.txt                # Loader dependencies
├── Dockerfile                      # Python 3.12-slim image
├── README.md                       # Deployment & usage guide
├── .env                            # Local secrets (never commit)
└── .gitignore
```

---

## Technical Standards

- **Language:** Python 3.12+
- **HTTP server:** Flask 3.0+ (used only for Cloud Run HTTP trigger mode)
- **Database driver:** `psycopg2-binary` (loader), `psycopg[binary]` async (categorizer)
- **Tests:** pytest — run with `pytest tests/ -v` from repo root
- **Tests must pass before deploy** — CI blocks deployment if any test fails
- **No mocking the database** in tests — tests that require real DB are deferred
- **Containerization:** Docker (Python 3.12-slim base image)
- **Secrets management:** GCP Secret Manager in production; `.env` file locally
- **Two separate `requirements.txt` files:** `requirements.txt` (loader, used by Docker) and `categorizer/requirements.txt` (categorizer, installed manually)

---

## Naming Conventions

### Files
- `snake_case.py` — all Python files: `gmail_poller.py`, `batch_process.py`, `train.py`
- Sub-modules organized by function: `models/`, `processing/`, `ingestion/`, `evaluation/`

### Functions & Methods
- `snake_case`: `get_connection()`, `parse_upi_debit()`, `create_tables()`
- Private helpers prefixed with `_`: `_build_gmail_service()`, `_parse_amount()`
- Format predicates: `is_upi_debit()`, `is_netbanking()`, `is_upi_credit()`
- DB operations: `get_connection()`, `create_tables()`, `is_already_processed()`, `insert_transaction()`

### Classes
- `PascalCase`: `MerchantMemory`, `TransactionParser` (if added)
- Internal/private classes: `_TextExtractor`

### Variables & Constants
- `snake_case` for local and module-level variables: `gmail_message_id`, `transaction_dict`
- `UPPER_CASE` for module-level constants: `HDFC_SENDERS`, `IST`, `GMAIL_SCOPES`, `DEFAULT_RULES_PATH`

### Transaction dict keys (canonical set)
```python
{
    "amount": Decimal,
    "type": "debit" | "credit",
    "format": "upi" | "netbanking" | "debit_card",
    "merchant": str,
    "date": datetime (UTC),
    "vpa": str | None,
    "upi_ref": str | None,
    "account_last4": str | None,
    "card_last4": str | None,
}
```

### Database
- Tables: `snake_case` — `transactions`, `processed_emails`, `data_feed_history`, `transaction_batches`, `transaction_batch_items`
- Columns: `snake_case` — `gmail_message_id`, `upi_ref`, `account_last4`, `raw_entry`
- Status enums (stored as VARCHAR): `'success' | 'skipped' | 'failed'` (processed_emails), `'pending' | 'reviewed' | 'complete'` (transaction_batches)
- Prediction source: `'memory' | 'rule' | 'ml' | 'none'`

---

## Key Dependencies

### Loader (`requirements.txt`)
| Package | Version | Purpose |
|---|---|---|
| `flask` | 3.0+ | HTTP server for Cloud Run trigger |
| `google-api-python-client` | 2.132.0 | Gmail API client |
| `google-auth` | 2.29.0 | Google authentication base |
| `google-auth-oauthlib` | 1.2.0 | OAuth2 flow for Gmail access |
| `psycopg2-binary` | 2.9.9 | PostgreSQL sync driver |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `python-dateutil` | 2.9.0.post0 | Date parsing utilities |
| `openpyxl` | 3.1+ | Excel file reading (migration tool) |

### Categorizer (`categorizer/requirements.txt`)
| Package | Purpose |
|---|---|
| `pandas` | DataFrame manipulation for training data |
| `scikit-learn` | TF-IDF vectorization, preprocessing |
| `lightgbm` | Hierarchical 3-stage classifier |
| `google-cloud-storage` | GCS model artifact store |
| `joblib` | Model serialization |
| `psycopg[binary]` | PostgreSQL async driver |
| `python-dotenv` | `.env` file loading |
| `openpyxl` | Excel reading |

---

## Environment Variables

### Loader
| Variable | Required | Description |
|---|---|---|
| `GMAIL_CLIENT_ID` | Yes | OAuth2 client ID from GCP Console |
| `GMAIL_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | Yes | Long-lived refresh token (generated by `auth.py`) |
| `DATABASE_URL` | Yes | Neon PostgreSQL connection string |
| `NOTIFICATION_EMAIL` | Yes | Recipient for nightly summary email |
| `POLL_DAYS` | No | Days back to search (default: `1`) — ignored if `AFTER_DATE` is set |
| `AFTER_DATE` | No | Gmail `after:` date filter in `YYYY/MM/DD` format; overrides `POLL_DAYS` for backfill runs |
| `MAX_MESSAGES` | No | Cap on messages processed (useful for testing) |
| `PORT` | No | Flask server port (default: `8080`) |
| `REVIEW_TOKEN` | No | If set, all `/review` and `/api/*` routes require `?token=<value>` or `Authorization: Bearer <value>` |

### Categorizer
| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes (or individual vars) | Full Neon connection string |
| `GCS_MODEL_BUCKET` | Yes | GCS bucket name for model storage (e.g. `hdfc-statement-loader-mlruns`) |
| `DB_HOST` | Alt | Used if `DATABASE_URL` not set |
| `DB_PORT` | Alt | Default: `5432` |
| `DB_NAME` | Alt | Database name |
| `DB_USER` | Alt | Database user |
| `DB_PASSWORD` | Alt | Database password |

---

## Database Schema

### `transactions` — parsed transaction records
```
id               SERIAL PRIMARY KEY
date             TIMESTAMPTZ
amount           NUMERIC(12, 2)
type             VARCHAR(6)          -- 'debit' or 'credit'
format           VARCHAR(20)         -- 'upi', 'netbanking', 'debit_card'
account_last4    CHAR(4)
card_last4       CHAR(4)
vpa              TEXT
merchant         TEXT
raw_entry        TEXT
upi_ref          VARCHAR(30)
gmail_message_id TEXT UNIQUE         -- idempotency key
created_at       TIMESTAMPTZ DEFAULT NOW()
```

### `processed_emails` — audit log for all processed message IDs
```
gmail_message_id TEXT PRIMARY KEY
processed_at     TIMESTAMPTZ
status           VARCHAR(10)         -- 'success', 'skipped', 'failed'
notes            TEXT
```

### `data_feed_history` — labeled training data & final categorized transactions
```
id           SERIAL PRIMARY KEY
entry_date   DATE NOT NULL
entry_text   TEXT NOT NULL
sub_category TEXT
category     TEXT
spend_type   VARCHAR(20)         -- 'Expense', 'Investment', 'Saving' (capitalised)
amount       NUMERIC(12, 2) NOT NULL
merchant     TEXT
vpa          TEXT
upi_ref      TEXT
created_at   TIMESTAMPTZ DEFAULT NOW()
```

### `transaction_batches` — batch lifecycle management
```
id               SERIAL PRIMARY KEY
row_count        INT
status           VARCHAR(20)         -- 'pending', 'reviewed', 'complete'
created_at       TIMESTAMPTZ DEFAULT NOW()
completed_at     TIMESTAMPTZ
```

### `transaction_batch_items` — per-transaction predictions (human-editable)
```
batch_id         INT REFERENCES transaction_batches(id)
transaction_id   INT REFERENCES transactions(id)
pred_category    VARCHAR
pred_subcategory VARCHAR
pred_type        VARCHAR
pred_confidence  DECIMAL(5,4)
pred_source      VARCHAR             -- 'memory', 'rule', 'ml', 'none'
category         VARCHAR             -- editable by human before commit
subcategory      VARCHAR             -- editable by human before commit
type             VARCHAR             -- editable by human before commit
```

**Idempotency:** `processed_emails` tracks every attempted message ID (including failed ones). `transactions` has a UNIQUE constraint on `gmail_message_id`. UPI duplicates are detected by `upi_ref`; others by `(amount, date, format, merchant)`.

---

## Running Tests

```bash
# From repo root
pytest tests/ -v
```

`tests/conftest.py` adds `loader/` to `sys.path` so tests can import `parser`, `db`, etc. directly.

Tests that require a real database or heavy mocking (e.g., `db.py`, `categorizer/`) are deferred — do not add database mocks to the test suite.

---

## CI/CD (GitHub Actions)

Workflow: `.github/workflows/deploy.yml` — triggered on push to `main`.

**Job 1 — `test`** (ubuntu-latest):
1. Setup Python 3.12
2. `pip install -r requirements.txt pytest`
3. `pytest tests/ -v`

**Job 2 — `deploy`** (runs only if `test` passes):
1. Authenticate to GCP via Workload Identity Federation (OIDC)
2. Build Docker image with buildx cache
3. Push to Artifact Registry: `asia-south1-docker.pkg.dev/hdfc-statement-loader/hdfc-loader/hdfc-statement-loader:latest`
4. Deploy to Cloud Run service `hdfc-statement-loader` (region: `asia-south1`)

**Required GitHub secrets:** `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`

---

## Deployment References

- **GCP project:** `hdfc-statement-loader`
- **Cloud Run service:** `hdfc-statement-loader` (region: `asia-south1`)
- **Artifact Registry:** `asia-south1-docker.pkg.dev/hdfc-statement-loader/hdfc-loader/`
- **Cloud Scheduler job:** `hdfc-statement-loader-daily` — cron `0 21 * * *` (UTC) = 9 PM IST daily
- **Database:** Neon managed PostgreSQL, database name `financial_db`

---

## Development Notes

### Email Parsing Pipeline
`loader/parser.py` detects 4 formats via regex against raw email text:
- `upi_debit` (old format): no VPA in subject
- `upi_debit` (new format): VPA present
- `upi_credit`: credit transactions
- `netbanking`: net banking debits
- `debit_card`: card swipe transactions

Each format has its own `parse_*()` function. The main `parse()` entry point returns a dict or `None`. All dates are stored as UTC. The parser has 40+ unit tests in `tests/test_parser.py` — always run tests after modifying parser logic.

### Categorization Fallback Chain
`categorizer/processing/pipeline.py` applies in order:
1. **Memory** (`memory.py`): exact merchant match from past classifications
2. **Rules** (`rules.py`): keyword match from `config/rules.json`
3. **ML model** (`models/predict.py`): 3-stage LightGBM (type → category → subcategory)
4. **Fallback**: `"Unknown"`

Model bundle is stored in GCS (`GCS_MODEL_BUCKET` env var, path `models/spend-classifier/champion.joblib`). If no model exists in GCS, `batch_process.py` will raise `FileNotFoundError` — run `python main.py` from the `categorizer/` directory with `GCS_MODEL_BUCKET` set to seed it. In Cloud Run, the service account authenticates to GCS automatically via IAM.

### Batch Review Workflow
The old manual SQL approach has been replaced by a web UI. Current workflow:

1. `python categorizer/batch_process.py` — creates batches of up to 25 items each with ML predictions (status: `pending`)
2. Open `/review` in a browser — select the batch from the sidebar
3. Edit `category`, `subcategory`, `type` inline via dropdowns — changes auto-save on every change (PATCH to API)
4. Click **Mark Reviewed** — sets batch status to `reviewed`
5. Click **Complete Batch** — inserts rows into `data_feed_history`, sets status to `complete`, triggers model retraining in background

**Review UI implementation files:**
- `loader/review.py` — Flask Blueprint registered on the main app; all API logic is here
- `templates/review.html` — Single-page UI served at `GET /review`
- Blueprint is registered in `loader/app.py` with `app.register_blueprint(review_bp)`

**Review API routes** (all in `loader/review.py`):
| Route | Description |
|---|---|
| `GET /review` | Serves the HTML page |
| `GET /api/batches` | Lists batches; append `?include_complete=1` to include completed ones |
| `GET /api/batches/<id>` | Batch info + all items joined with transactions |
| `PATCH /api/batches/<id>/items/<txn_id>` | Save category/subcategory/type for one item |
| `DELETE /api/batches/<id>/items/<txn_id>` | Remove one item from batch, decrements row_count |
| `POST /api/batches/<id>/mark-reviewed` | Transitions batch pending → reviewed |
| `POST /api/batches/<id>/complete` | Inserts into data_feed_history, triggers retraining |
| `GET /api/categories` | Returns `{categories, types}` merged from rules.json + data_feed_history |

**UI behaviour notes:**
- Category, subcategory, and type use a custom combo: clicking shows a full dropdown, typing filters it, any free-text value is accepted
- Dropdown options are sourced from `GET /api/categories` (merged rules.json + data_feed_history) and populated at page load
- Subcategory options update automatically when category changes
- Input changes fire a PATCH immediately (auto-save, no submit button)
- Orange hint text under an input signals the value differs from the ML prediction
- Revert button (↩) resets all three fields for a row back to ML prediction values
- Delete button (🗑) removes the row from the batch entirely (DELETE API + live row count update)
- Sidebar "Show all" toggle reveals completed batches; selecting a completed batch shows a read-only view with no action buttons
- Complete Batch button is disabled until the batch is marked reviewed


### SQL Migration Scripts
Never run SQL migration or setup scripts against the database without first asking the user for confirmation and any required inputs (connection strings, target tables, etc.).
