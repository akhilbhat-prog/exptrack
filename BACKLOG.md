# Backlog — hdfc-statement-loader

Items to be built in future sessions, in rough priority order.

---

## BL-1 · Verify filter repaging across the full period (VIEW)

**Status:** Needs user testing  
`onFilter()` resets `viewPage=1` and `getDisplayItems()` slices from the fully-filtered array, so rows matching a filter should consolidate to page 1 regardless of which server page they were on. Needs a real-data smoke test on a period with > 25 rows.

---

## BL-2 · Verify sort-across-pages (VIEW)

**Status:** Needs user testing  
Sort operates on the full `currentItems` array (entire period loaded via `page_size=5000`) before slicing. Sorting by Amount desc should always put the highest row on page 1. Needs a real-data smoke test.

---

## BL-3 · Monthly autopay / recurring spend tracker

**Status:** Not started  
Track expenses that repeat every month and are set up as autopay (subscriptions, EMIs, rent). Show expected-vs-actual per month and flag if a known recurring item is missing.

Rough design:
- `cadence='A'` rows in `data_feed_history` already represent monthly-recurring semantics
- Add a sidebar card or dedicated section on `/view` listing all `cadence='A'` items grouped by merchant, showing last-seen date and expected next date
- "Missing this month" indicator when a recurring item has no matching row in the current period

---

## BL-4 · Bulk-edit shared & amortised transactions from April 2025

**Status:** Not started  
Retroactively mark existing `data_feed_history` rows (April 2025 onwards) with `shared_expense='Y'` and/or `cadence='A'` / `divide_by=12`. Options:
- Extend the bulk-edit bar on `/view` to include Cadence and Shared fields (server recomputes monthly_amount / final_amount on bulk PATCH)
- One-shot data migration script (requires user confirmation before running — per SQL-scripts policy)

---

## BL-5 · Make default share ratio and autopay divisor configurable

**Status:** Not started  
Currently hardcoded in `templates/view.html`:
- Shared toggle on → `share_ratio = 0.7`
- Cadence `A` → `divide_by = 12`

Work: store user-preferred defaults in `localStorage` (lightweight, no backend needed). Add a small settings panel to `/view` where the user can adjust these. Read them in `onSharedExpenseChange()` and the cadence-A handler.

---

## BL-6 · Shared transaction mirror table

**Status:** Awaiting requirements  
Shared transactions (`shared_expense='Y'`) should be copied to a separate table for tracking (e.g. split-expense reconciliation). Details to be provided by the user in a future session.

Open questions:
- Table name and schema
- Trigger: on insert, on PATCH to shared=Y, or manual?
- Should updates to the source row sync to the mirror?
- Who/what consumes this table?
