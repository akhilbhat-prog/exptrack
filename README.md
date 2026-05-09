# HDFC Statement Loader

A Gmail-to-PostgreSQL pipeline that polls HDFC Bank transaction alert emails
daily and stores parsed transactions in a Neon PostgreSQL database.  Runs as a
Google Cloud Run **Service** triggered by Cloud Scheduler, and also accepts
on-demand HTTP requests.

---

## How it works

1. **Gmail poller** (`gmail_poller.py`) authenticates with the Gmail API using an
   OAuth2 refresh token and searches for emails from `alerts@hdfcbank.bank.in` or `alerts@hdfcbank.net` (both used by HDFC) newer than `POLL_DAYS` days.
2. **Parser** (`parser.py`) detects the email format (UPI debit/credit,
   NetBanking, Debit Card) and extracts structured fields.
3. **DB layer** (`db.py`) writes the transaction to Neon PostgreSQL and records
   each Gmail message ID in `processed_emails` so re-runs are fully idempotent.
4. After each run, a **summary email** is sent to `NOTIFICATION_EMAIL` with
   transaction details and parser test results.

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
| `GMAIL_REFRESH_TOKEN` | Long-lived refresh token (needs `gmail.readonly` + `gmail.send`) |
| `DATABASE_URL` | Neon connection string, e.g. `postgresql://user:pass@host/db?sslmode=require` |
| `NOTIFICATION_EMAIL` | Gmail address to receive the nightly summary email |
| `POLL_DAYS` | How many days back to search (default: `1`) |

### Obtaining / re-obtaining Gmail OAuth2 credentials

1. In [Google Cloud Console](https://console.cloud.google.com), create an
   **OAuth 2.0 Client ID** of type *Desktop app*.
2. Download the JSON as `credentials.json`.
3. Run the one-time authorisation flow:

   ```bash
   python auth.py
   ```

   A browser window will open. Grant both **Read** and **Send** Gmail permissions.
   Copy the printed `GMAIL_REFRESH_TOKEN` into your `.env`.

4. If you ever need to re-authorise (e.g. after revoking access), repeat step 3
   and update the token in your `.env` and in GCP Secret Manager.

---

## Local testing

```bash
# 1. Copy and fill in .env
cp .env.example .env   # or create manually

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the parser unit tests (no network or DB required)
python parser.py

# 4. Run the full pipeline (also sends the summary email)
python gmail_poller.py

# 5. Test the HTTP server locally
PORT=8080 python gmail_poller.py
# In another terminal:
curl -X POST http://localhost:8080/
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
  -e NOTIFICATION_EMAIL="you@gmail.com" \
  -e POLL_DAYS=1 \
  hdfc-statement-loader
```

---

## Google Cloud Run deployment

### 1. Authenticate and configure

```bash
gcloud auth login
gcloud config set project hdfc-statement-loader
```

### 2. Create an Artifact Registry repository (first time only)

```bash
gcloud artifacts repositories create hdfc-loader \
  --repository-format=docker \
  --location=asia-south1
```

### 3. Build and push the image

```bash
IMAGE="asia-south1-docker.pkg.dev/hdfc-statement-loader/hdfc-loader/hdfc-statement-loader:latest"

gcloud builds submit --tag "$IMAGE"
# or, if using Docker locally:
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

### 4. Deploy as a Cloud Run Service

```bash
SA="hdfc-loader-invoker@hdfc-statement-loader.iam.gserviceaccount.com"

gcloud run deploy hdfc-statement-loader \
  --image "$IMAGE" \
  --region asia-south1 \
  --no-allow-unauthenticated \
  --set-secrets \
    GMAIL_CLIENT_ID=gmail-client-id:latest,\
    GMAIL_CLIENT_SECRET=gmail-client-secret:latest,\
    GMAIL_REFRESH_TOKEN=gmail-refresh-token:latest,\
    DATABASE_URL=neon-database-url:latest \
  --set-env-vars POLL_DAYS=1,NOTIFICATION_EMAIL=you@gmail.com \
  --timeout 300s
```

> **Tip:** store secrets in [Secret Manager](https://cloud.google.com/secret-manager)
> rather than passing them as plain env vars.  The `--set-secrets` flag above
> assumes you have already created secrets named `gmail-client-id` etc.

After deployment, `gcloud` will print the **Service URL** — save it for the next steps.

### 5. Schedule daily execution with Cloud Scheduler

The cron below fires at **21:00 IST** every day.

```bash
# Create a service account (first time only)
SA="hdfc-loader-invoker@hdfc-statement-loader.iam.gserviceaccount.com"

gcloud iam service-accounts create hdfc-loader-invoker \
  --display-name "HDFC Loader Cloud Run Invoker"

gcloud run services add-iam-policy-binding hdfc-statement-loader \
  --region asia-south1 \
  --member "serviceAccount:${SA}" \
  --role "roles/run.invoker"

# Create the scheduler job (replace SERVICE_URL with the URL from step 4)
SERVICE_URL="https://hdfc-statement-loader-<hash>-el.a.run.app"

gcloud scheduler jobs create http hdfc-statement-loader-daily \
  --location asia-south1 \
  --schedule "0 21 * * *" \
  --time-zone "Asia/Kolkata" \
  --uri "${SERVICE_URL}" \
  --http-method POST \
  --oidc-service-account-email "${SA}" \
  --oidc-token-audience "${SERVICE_URL}"
```

### 6. On-demand trigger

To trigger a run manually from the command line:

```bash
SERVICE_URL="https://hdfc-statement-loader-<hash>-el.a.run.app"

curl -X POST "${SERVICE_URL}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

The response is immediate JSON with the run outcome:

```json
{
  "status": "ok",
  "processed": 2,
  "skipped": 0,
  "failed": 0,
  "message": "2 transaction(s) processed."
}
```

Or when nothing new was found:

```json
{
  "status": "ok",
  "processed": 0,
  "skipped": 0,
  "failed": 0,
  "message": "No new transactions found."
}
```

---

## Checking Cloud Run logs

```bash
# List recent revisions / requests
gcloud run services describe hdfc-statement-loader --region asia-south1

# Stream logs
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="hdfc-statement-loader"' \
  --limit 200 \
  --format "value(textPayload)" \
  --freshness 1d
```

Or open **Cloud Logging** in the console and filter by:
```
resource.type="cloud_run_revision"
resource.labels.service_name="hdfc-statement-loader"
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
├── gmail_poller.py    # Gmail API polling, HTTP server, email notifications
├── auth.py            # One-time OAuth2 flow to obtain refresh token
├── Dockerfile         # python:3.12-slim image
├── requirements.txt   # Pinned Python dependencies
└── README.md
```
