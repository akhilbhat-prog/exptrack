# Backlog

## BL-1 — Fix filter repaging (`/view`)

**Status:** Complete (verified 2026-05-28 — filter correctly resets to page 1 and repaginates from the full in-memory dataset)

---

## BL-2 — User test: sort across pages (`/view`)

**Status:** Complete (verified 2026-05-28 — sort applies to full in-memory dataset and repaginates correctly)

---

## BL-3 — Monthly autopay / recurring spend tracker

**Status:** Open

Build logic to detect transactions that repeat every month (autopay / standing instructions). Surface them in the UI so the user can mark them as recurring and track them separately from one-off spends. Requirements TBD.

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
