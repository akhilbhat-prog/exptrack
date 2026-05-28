# Backlog

## BL-1 — Fix filter repaging (`/view`)

**Status:** Complete (verified 2026-05-28 — filter correctly resets to page 1 and repaginates from the full in-memory dataset)

---

## BL-2 — User test: sort across pages (`/view`)

**Status:** Complete (verified 2026-05-28 — sort applies to full in-memory dataset and repaginates correctly)

---

## BL-3 — Multi-period Add Entry for Cadence = A (`/view`)

**Status:** Complete (2026-05-28)

When adding an entry with cadence=A and divide_by=N, the backend now creates N rows automatically: the first with the user's entered date (current period), and the remaining N-1 with entry_date set to the 1st of each subsequent month. All rows are independent — editing or deleting one does not affect the others. Toast confirms "N entries added (N months)".

---

## BL-4 — Backfill shared & amortised rows from April 2025

**Status:** Open

User needs to add and/or edit shared and amortised transactions dating back to the start of tracking (April 2025). Likely a bulk-edit workflow on `/view` or a dedicated import/correction flow.

---

## BL-5 — Configurable share ratio and annual divisor defaults

**Status:** Open

The default share ratio (0.7) and annual cadence divisor (12 for cadence A) are hardcoded in the UI. Make them user-configurable — either via a settings table in the DB, a config file, or a settings endpoint — so the user can change them without a code deploy.

---

## BL-6 — Shared transaction mirror table

**Status:** Open (requirements pending)

When a transaction is marked as shared, copy it to a separate table to track the counterparty's portion independently. Full schema and workflow requirements to be defined.
