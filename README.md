# HDFC Statement Loader

A Gmail-to-PostgreSQL pipeline that polls HDFC Bank transaction alert emails
daily and stores parsed transactions in a Neon PostgreSQL database.  Runs as a
Google Cloud Run Job triggered by Cloud Scheduler.

---

## How it works

1. **Gmail poller** (`gmail_poller.py`) authenticates with the Gmail API using an
   OAuth2 refresh token and searches for emails from `alerts@hdfcbank.bank.in` or `alerts@hdfcbank.net` (both used by HDFC) newer than `POLL_DAYS` days.
2. **Parser** (`parser.py`) detects the email format (UPI debit/credit,
   NetBanking, Debit Card) and extracts structured fields.
3. **DB layer** (`db.py`) writes the transaction to Neon PostgreSQL and records
   each Gmail message ID in `processed_emails` so re-runs are fully idempotent.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.12+ |
| Docker | 24+ |
| Google Cloud SDK (`gcloud`) | latest |
| A [Neon](https://neon.tech) project | — |
| A Google Cloud project with the Gmail API enabled | — |

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `GMAIL_CLIENT_ID` | OAuth2 client ID from Google Cloud Console |
| `GMAIL_CLIENT_SECRET` | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | Long-lived refresh token for the Gmail account |
| `DATABASE_URL` | Neon connection string, e.g. `postgresql://user:pass@host/db?sslmode=require` |
| `POLL_DAYS` | How many days back to search (default: `1`) |

### Obtaining Gmail OAuth2 credentials

1. In [Google Cloud Console](https://console.cloud.google.com), create an
   **OAuth 2.0 Client ID** of type *Desktop app*.
2. Download the JSON, note `client_id` and `client_secret`.
3. Run the one-time authorisation flow to get a refresh token:

   ```bash
   pip install google-auth-oauthlib
   python - <<'EOF'
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_secrets_file(
       "credentials.json",
       scopes=["https://www.googleapis.com/auth/gmail.readonly"],
   )
   creds = flow.run_local_server(port=0)
   print("Refresh token:", creds.refresh_token)
   EOF
   ```

4. Store the printed refresh token as `GMAIL_REFRESH_TOKEN`.

---

## Local testing

```bash
# 1. Set environment variables
export GMAIL_CLIENT_ID="..."
export GMAIL_CLIENT_SECRET="..."
export GMAIL_REFRESH_TOKEN="..."
export DATABASE_URL="postgresql://..."
export POLL_DAYS=7   # look back 7 days for initial test

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the parser unit tests (no network or DB required)
python parser.py

# 4. Run the full pipeline
python gmail_poller.py
```

---

## Docker

```bash
# Build
docker build -t hdfc-statement-loader .

# Run (pass env vars inline or via --env-file)
docker run --rm \
  -e GMAIL_CLIENT_ID="..." \
  -e GMAIL_CLIENT_SECRET="..." \
  -e GMAIL_REFRESH_TOKEN="..." \
  -e DATABASE_URL="postgresql://..." \
  -e POLL_DAYS=1 \
  hdfc-statement-loader
```

---

## Google Cloud Run deployment

### 1. Authenticate and configure

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Create an Artifact Registry repository

```bash
gcloud artifacts repositories create hdfc-loader \
  --repository-format=docker \
  --location=asia-south1
```

### 3. Build and push the image

```bash
IMAGE="asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/hdfc-loader/hdfc-statement-loader:latest"

gcloud builds submit --tag "$IMAGE"
# or, if using Docker locally:
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

### 4. Create the Cloud Run Job

```bash
gcloud run jobs create hdfc-statement-loader \
  --image "$IMAGE" \
  --region asia-south1 \
  --set-secrets \
    GMAIL_CLIENT_ID=gmail-client-id:latest,\
    GMAIL_CLIENT_SECRET=gmail-client-secret:latest,\
    GMAIL_REFRESH_TOKEN=gmail-refresh-token:latest,\
    DATABASE_URL=neon-database-url:latest \
  --set-env-vars POLL_DAYS=1 \
  --max-retries 2 \
  --task-timeout 300s
```

> **Tip:** store secrets in [Secret Manager](https://cloud.google.com/secret-manager)
> rather than passing them as plain env vars.  The `--set-secrets` flag above
> assumes you have already created secrets named `gmail-client-id` etc.

#### Manual test run

```bash
gcloud run jobs execute hdfc-statement-loader --region asia-south1 --wait
```

### 5. Schedule daily execution with Cloud Scheduler

The cron below fires at **06:00 IST** every day (= 00:30 UTC).

```bash
# Create a service account for the scheduler to invoke the job
SA="hdfc-loader-invoker@YOUR_PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create hdfc-loader-invoker \
  --display-name "HDFC Loader Cloud Run Invoker"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member "serviceAccount:${SA}" \
  --role "roles/run.invoker"

# Create the scheduler job
gcloud scheduler jobs create http hdfc-statement-loader-daily \
  --location asia-south1 \
  --schedule "0 6 * * *" \
  --time-zone "Asia/Kolkata" \
  --uri "https://run.googleapis.com/v2/projects/YOUR_PROJECT_ID/locations/asia-south1/jobs/hdfc-statement-loader:run" \
  --http-method POST \
  --oauth-service-account-email "${SA}"
```

---

## Checking Cloud Run logs

```bash
# Logs for the most recent execution
gcloud run jobs executions list \
  --job hdfc-statement-loader \
  --region asia-south1 \
  --limit 5

# Stream logs for a specific execution
gcloud logging read \
  'resource.type="cloud_run_job" resource.labels.job_name="hdfc-statement-loader"' \
  --limit 200 \
  --format "value(textPayload)" \
  --freshness 1d
```

Or open **Cloud Logging** in the console and filter by:
```
resource.type="cloud_run_job"
resource.labels.job_name="hdfc-statement-loader"
```

---

## Querying the Neon database

Connect with `psql` or any PostgreSQL client using your `DATABASE_URL`.

```sql
-- Recent transactions
SELECT date, type, format, amount, merchant, account_last4, card_last4
FROM transactions
ORDER BY date DESC
LIMIT 20;

-- Monthly spend summary
SELECT
    DATE_TRUNC('month', date) AS month,
    SUM(CASE WHEN type = 'debit'  THEN amount ELSE 0 END) AS total_debits,
    SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) AS total_credits
FROM transactions
GROUP BY 1
ORDER BY 1 DESC;

-- Idempotency log: last 10 processed emails
SELECT gmail_message_id, processed_at, status, notes
FROM processed_emails
ORDER BY processed_at DESC
LIMIT 10;
```

---

## Project structure

```
hdfc-statement-loader/
├── parser.py          # Email format detection and field extraction
├── db.py              # PostgreSQL schema, queries, idempotency helpers
├── gmail_poller.py    # Gmail API polling and orchestration (entry point)
├── Dockerfile         # python:3.12-slim image
├── requirements.txt   # Pinned Python dependencies
└── README.md
```
