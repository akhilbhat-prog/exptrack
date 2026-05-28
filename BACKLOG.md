# Backlog

## BL-1 — Fix filter repaging (`/view`)

**Status:** Open

When a filter is applied on `/view`, the filtered result set must re-paginate from page 1. Currently the page cursor is not reset when a filter input changes, so matching rows can be spread across pages (e.g. 15 rows matching a category appearing on pages 1, 2, and 3 instead of all on page 1).

**Fix:** In `templates/view.html`, reset `currentPage = 1` inside the filter-change handler before calling `applyFiltersAndRender()`.

---

## BL-2 — User test: sort across pages (`/view`)

**Status:** Open (manual verification by user)

Verify that column sorting on `/view` applies to the full in-memory dataset for the period (all rows loaded in the client-side `allRows` array) and not just the rows on the current page. Sort then re-paginate — page 1 should show the globally top-N rows for the chosen sort key.

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
