import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, CreditCard, Download, X, ChevronDown, ChevronRight } from 'lucide-react'
import { Layout } from '../components/Layout'
import { NumberInput, validNumber, numberError } from '../components/NumberInput'
import { useToast } from '../hooks/useToast'
import { sharedApi, type CreateSharedPayload, type PaymentPayload } from '../api/shared'
import type { SharedRow, SharedSummary } from '../types'

function fmtAmt(n: number)  { return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

type SortKey = keyof Pick<SharedRow, 'entry_date' | 'amount' | 'balance' | 'merchant' | 'category'>

// Unsaved edits for one row. amount/share_ratio are null while their field is blank or invalid.
type SharedEdits = Partial<Omit<SharedRow, 'amount' | 'share_ratio'>> & { amount?: number | null; share_ratio?: number | null }

export function SharedPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const [fy, setFy] = useState<number | null>(null)
  const [month, setMonth] = useState<string | null>(null)   // 'YYYY-MM' inside the FY, or null for the whole FY
  const [split, setSplit] = useState(true)                    // one table per payer (FY or month)
  const [expandedFys, setExpandedFys] = useState<Set<number>>(new Set())
  const [sortCol, setSortCol]   = useState<SortKey>('entry_date')
  const [sortDir, setSortDir]   = useState<'asc' | 'desc'>('desc')
  const [filter, setFilter]     = useState('')
  const [pending, setPending]   = useState<Record<number, SharedEdits>>({})
  const [addModal, setAddModal] = useState(false)
  const [payModal, setPayModal] = useState(false)

  const { data: fyList = [] } = useQuery({
    queryKey: ['shared-fy'],
    queryFn: sharedApi.fyList,
    select: (list) => {
      if (!fy && list.length) setFy(list[0])
      return list
    },
  })

  const activeFy = fy ?? fyList[0] ?? new Date().getFullYear()

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['shared', activeFy],
    queryFn: () => sharedApi.list(activeFy),
    enabled: !!activeFy,
  })

  const { data: summary } = useQuery({
    queryKey: ['shared-summary', activeFy, month],
    queryFn: () => sharedApi.summary(activeFy, month),
    enabled: !!activeFy,
  })

  const { data: monthList = [] } = useQuery({
    queryKey: ['shared-months'],
    queryFn: sharedApi.months,
  })

  const patchMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Parameters<typeof sharedApi.patch>[1] }) =>
      sharedApi.patch(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] })
      qc.invalidateQueries({ queryKey: ['shared-months'] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: sharedApi.delete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] })
      qc.invalidateQueries({ queryKey: ['shared-months'] }); toast('Deleted', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function sort(col: SortKey) {
    setSortDir(sortCol === col && sortDir === 'asc' ? 'desc' : 'asc')
    setSortCol(col)
  }

  function sortArrow(col: SortKey) {
    if (sortCol !== col) return ''
    return sortDir === 'asc' ? ' ▲' : ' ▼'
  }

  const monthRows = useMemo(
    () => (month ? rows.filter(row => (row.entry_date ?? '').startsWith(month)) : rows),
    [rows, month],
  )

  const displayed = useMemo(() => {
    let r = [...rows]
    if (month) r = r.filter(row => (row.entry_date ?? '').startsWith(month))
    if (filter) {
      const q = filter.toLowerCase()
      r = r.filter(row =>
        (row.merchant ?? '').toLowerCase().includes(q) ||
        (row.entry_text ?? '').toLowerCase().includes(q) ||
        (row.category ?? '').toLowerCase().includes(q)
      )
    }
    r.sort((a, b) => {
      const av = a[sortCol] ?? '', bv = b[sortCol] ?? ''
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
    return r
  }, [rows, month, filter, sortCol, sortDir])

  function setPend(id: number, field: keyof SharedRow, value: unknown) {
    setPending(p => ({ ...p, [id]: { ...p[id], [field]: value } }))
  }

  function saveRow(row: SharedRow) {
    const edits = pending[row.id] ?? {}
    if (!Object.keys(edits).length) return
    if ('amount' in edits && !validNumber('amount', edits.amount)) { toast(numberError('Amount', 'amount'), 'error'); return }
    if ('share_ratio' in edits && !validNumber('ratio', edits.share_ratio)) { toast(numberError('Ratio', 'ratio'), 'error'); return }
    const payload = { amount: edits.amount ?? undefined, share_ratio: edits.share_ratio ?? undefined, paid_by: edits.paid_by }
    patchMut.mutate({ id: row.id, payload }, {
      onSuccess: () => toast(
        edits.amount !== undefined && row.divide_by > 1
          ? `Saved: all ${row.divide_by} months of this series re-spread in History`
          : 'Saved', 'success'),
    })
    setPending(p => { const n = { ...p }; delete n[row.id]; return n })
  }

  function isDirty(id: number) { return !!Object.keys(pending[id] ?? {}).length }

  function get<K extends keyof SharedRow>(row: SharedRow, k: K): SharedRow[K] {
    return (pending[row.id]?.[k] as SharedRow[K]) ?? row[k]
  }

  const fyLabel = (y: number) => `${y}–${String(y + 1).slice(2)}`
  const monthLabel = (m: string) =>
    new Date(`${m}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
  const monthsOf = (y: number) => monthList.filter(m => m.fy === y)   // already newest first
  const isOpen = (y: number) => expandedFys.has(y) || (y === activeFy && month != null)
  function toggleFy(y: number) {
    setExpandedFys(prev => { const n = new Set(prev); if (isOpen(y)) n.delete(y); else n.add(y); return n })
  }

  const sidebar = (
    <>
      <div className="sidebar-header">Financial Year</div>
      {fyList.map(y => (
        <div key={y}>
          <div
            className={`fy-item${activeFy === y && !month ? ' active' : ''}`}
            style={{ display: 'flex', alignItems: 'center', gap: 4 }}
            onClick={() => { setFy(y); setMonth(null) }}
          >
            <button className="sidebar-chevron" title={isOpen(y) ? 'Collapse' : 'Expand'}
              onClick={e => { e.stopPropagation(); toggleFy(y) }}>
              {isOpen(y) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            FY {fyLabel(y)}
          </div>
          {isOpen(y) && monthsOf(y).map(m => (
            <div
              key={m.month}
              className={`fy-item fy-item-child${activeFy === y && month === m.month ? ' active' : ''}`}
              onClick={() => { setFy(y); setMonth(m.month) }}
            >
              <span>{monthLabel(m.month)}</span>
              <span className="fy-item-count">{m.count}</span>
            </div>
          ))}
        </div>
      ))}
    </>
  )

  return (
    <Layout
      sidebar={sidebar}
      headerExtra={
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => window.open(sharedApi.exportUrl(), '_blank')}>
            <Download size={13} /> Download All
          </button>
          <button className="btn btn-secondary btn-sm" onClick={() => setPayModal(true)}>
            <CreditCard size={13} /> Payment
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => setAddModal(true)}>
            <Plus size={13} /> Add Entry
          </button>
        </div>
      }
    >
      {/* Settle-up panel (FY or month), shown in both views */}
      {month
        ? <SettleUpPanel rows={monthRows} title={monthLabel(month)} periodLabel={monthLabel(month).split(' ')[0]}
            carriedFrom="previous months" summary={summary} />
        : <SettleUpPanel rows={monthRows} title={`FY ${fyLabel(activeFy)}`} periodLabel={`FY ${fyLabel(activeFy)}`}
            carriedFrom="previous FYs" summary={summary} />}

      {/* Table */}
      <div className="card">
        <div className="card-header" style={{ gap: 8 }}>
          <span>Shared Transactions — FY {fyLabel(activeFy)}{month ? ` · ${monthLabel(month)}` : ''}</span>
          <label className="btn btn-secondary btn-sm" style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input type="checkbox" checked={split} onChange={e => setSplit(e.target.checked)} />
            Split view
          </label>
          <input
            className="field-input"
            placeholder="Filter…"
            style={{ width: 200, fontSize: 12 }}
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>
        {isLoading ? (
          <div className="empty-state">Loading…</div>
        ) : displayed.length === 0 ? (
          <div className="empty-state">No shared transactions</div>
        ) : split ? (
          <SplitViews
            rows={displayed}
            editor={{ pending, setPend, isDirty, saveRow }}
            onIgnore={row => patchMut.mutate({ id: row.id, payload: { is_ignored: !row.is_ignored } })}
            onDelete={row => { if (confirm('Delete?')) deleteMut.mutate(row.id) }}
          />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th className="sortable sort-active" onClick={() => sort('entry_date')}>Date{sortArrow('entry_date')}</th>
                  <th className="sortable" onClick={() => sort('merchant')}>Merchant{sortArrow('merchant')}</th>
                  <th className="sortable" onClick={() => sort('category')}>Category{sortArrow('category')}</th>
                  <th className="sortable" style={{ textAlign: 'right' }} onClick={() => sort('amount')}>Amount{sortArrow('amount')}</th>
                  <th style={{ textAlign: 'right' }}>Mo. Amt</th>
                  <th style={{ textAlign: 'right' }}>Ratio</th>
                  <th style={{ textAlign: 'right' }} title="Mo. Amt × ratio (Akhil's share), as in History">Final Amt</th>
                  <th style={{ textAlign: 'right' }}>Aditi</th>
                  <th>Paid By</th>
                  <th className="sortable" style={{ textAlign: 'right' }} onClick={() => sort('balance')}>Balance{sortArrow('balance')}</th>
                  <th>Settled</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {displayed.map(row => {
                  const dirty = isDirty(row.id)
                  const c = liveCalc(row, pending[row.id])
                  const settled = get(row, 'settled') ?? row.settled
                  const ignored = get(row, 'is_ignored') ?? row.is_ignored

                  return (
                    <tr
                      key={row.id}
                      className={dirty ? 'dirty' : ''}
                      style={{
                        opacity: ignored ? 0.3 : settled ? 0.6 : 1,
                        background: row.is_payment ? 'var(--teal-dim)' : undefined,
                      }}
                    >
                      <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>{fmtDate(row.entry_date)}</td>
                      <td>
                        <div>{row.merchant ?? row.entry_text}</div>
                        {row.category && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{row.category}</div>}
                      </td>
                      <td style={{ color: 'var(--muted)' }}>{row.category ?? '—'}</td>
                      <td style={{ textAlign: 'right' }}>
                        <AmountInput row={row} edits={pending[row.id]} onChange={v => setPend(row.id, 'amount', v)} />
                      </td>
                      <td className="amt"><MonthlyCell row={row} mo={c.mo} /></td>
                      <td style={{ textAlign: 'right' }}>
                        {row.is_payment ? '—' : <RatioInput row={row} edits={pending[row.id]} onChange={v => setPend(row.id, 'share_ratio', v)} />}
                      </td>
                      <td className="amt">{row.is_payment ? '—' : fmtAmt(c.akhil)}</td>
                      <td className="amt">{row.is_payment ? '—' : fmtAmt(c.aditi)}</td>
                      <td>
                        {row.is_payment ? (
                          <span style={{ color: 'var(--teal)', fontSize: 12 }}>Payment</span>
                        ) : (
                          <PaidBySelect value={c.paidBy} onChange={v => setPend(row.id, 'paid_by', v)} />
                        )}
                      </td>
                      {row.is_payment ? (
                        <td className="amt" style={{ color: 'var(--green)', fontWeight: 600 }} title="Settlement, not a shared expense">
                          Settlement {fmtSigned(settleEffect({ ...row, amount: c.amount }))}
                        </td>
                      ) : (
                        <td className="amt" style={{ color: c.balance > 0 ? 'var(--red)' : 'var(--green)', fontWeight: 600 }}>
                          {fmtAmt(c.balance)}
                        </td>
                      )}
                      <td>
                        <input
                          type="checkbox" checked={!!settled}
                          onChange={() => patchMut.mutate({ id: row.id, payload: { settled: !settled } })}
                          style={{ cursor: 'pointer' }}
                        />
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {dirty && (
                            <button className="btn btn-primary btn-sm" onClick={() => saveRow(row)}>Update</button>
                          )}
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ color: ignored ? 'var(--muted)' : 'var(--amber)', fontSize: 11 }}
                            onClick={() => patchMut.mutate({ id: row.id, payload: { is_ignored: !ignored } })}
                            title={ignored ? 'Include in balance' : 'Ignore from balance'}
                          >
                            {ignored ? 'Include' : 'Ignore'}
                          </button>
                          {!row.history_id && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => { if (confirm('Delete?')) deleteMut.mutate(row.id) }}
                            >×</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Entry Modal */}
      {addModal && (
        <AddEntryModal
          onClose={() => setAddModal(false)}
          onSave={(rows) => {
            sharedApi.create(rows)
              .then(r => { toast(`Added ${r.count} entries`, 'success'); qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] }); qc.invalidateQueries({ queryKey: ['shared-months'] }); setAddModal(false) })
              .catch((e: Error) => toast(e.message, 'error'))
          }}
        />
      )}

      {/* Payment Modal */}
      {payModal && (
        <PaymentModal
          onClose={() => setPayModal(false)}
          onSave={(payload) => {
            sharedApi.payment(payload)
              .then(() => { toast('Payment recorded', 'success'); qc.invalidateQueries({ queryKey: ['shared'] }); qc.invalidateQueries({ queryKey: ['shared-summary'] }); qc.invalidateQueries({ queryKey: ['shared-months'] }); setPayModal(false) })
              .catch((e: Error) => toast(e.message, 'error'))
          }}
        />
      )}
    </Layout>
  )
}

function ratioLabel(r: number) {
  const a = Math.round(r * 100)
  return `${a}:${100 - a}`
}

const r2 = (n: number) => Math.round(n * 100) / 100

// A leading minus for negatives, e.g. −₹32,000.00
function fmtSigned(n: number) { return n < 0 ? `−${fmtAmt(-n)}` : fmtAmt(n) }

// Effect of a settlement on "Aditi owes Akhil": Aditi paying reduces it, Akhil paying increases it.
function settleEffect(r: SharedRow) { return r.paid_by === 'Aditi' ? -r.amount : r.amount }

// Row values with any unsaved edits applied, so computed columns update live before Update.
// A blank/invalid field (null) falls back to the saved value for the computed columns.
// Mo. Amt = Amount / the History row's divisor (a cadence-A lump sum is spread over its series).
function liveCalc(r: SharedRow, e: SharedEdits = {}) {
  const amount = e.amount ?? r.amount
  const ratio = e.share_ratio ?? r.share_ratio
  const paidBy = e.paid_by ?? r.paid_by
  const mo = e.amount == null ? (r.monthly_amount ?? r.amount) : r2(amount / (r.divide_by || 1))
  const akhil = r.is_payment ? 0 : r2(mo * ratio)
  const aditi = r.is_payment ? 0 : r2(mo * (1 - ratio))
  const owed = paidBy === 'Akhil' ? aditi : akhil
  return { amount, ratio, paidBy, mo, akhil, aditi, own: paidBy === 'Akhil' ? akhil : aditi, owed,
           balance: r.is_payment ? amount : owed }
}

// The field shows the edit if there is one (even a blank one), otherwise the saved value.
function editedValue(row: SharedRow, edits: SharedEdits | undefined, k: 'amount' | 'share_ratio'): number | null {
  return edits && k in edits ? (edits[k] ?? null) : row[k]
}

function AmountInput({ row, edits, onChange }: { row: SharedRow; edits?: SharedEdits; onChange: (v: number | null) => void }) {
  return (
    <NumberInput
      kind="amount" value={editedValue(row, edits, 'amount')} onChange={onChange}
      style={{ width: 96, padding: '3px 6px', fontSize: 12, textAlign: 'right' }}
      title={row.divide_by > 1 ? `Lump sum spread over ${row.divide_by} months; saving re-spreads the whole series` : undefined}
    />
  )
}

function MonthlyCell({ row, mo }: { row: SharedRow; mo: number }) {
  return (
    <>
      {fmtAmt(mo)}
      {row.divide_by > 1 && <div style={{ fontSize: 11, color: 'var(--muted)' }}>÷{row.divide_by}</div>}
    </>
  )
}

function RatioInput({ row, edits, onChange }: { row: SharedRow; edits?: SharedEdits; onChange: (v: number | null) => void }) {
  return (
    <NumberInput
      kind="ratio" value={editedValue(row, edits, 'share_ratio')} onChange={onChange}
      style={{ width: 64, padding: '3px 6px', fontSize: 12 }}
      title="Akhil's share, 0 to 1"
    />
  )
}

function PaidBySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select className="field-input" style={{ padding: '3px 6px', fontSize: 12 }} value={value}
      onChange={e => onChange(e.target.value)}>
      <option>Akhil</option>
      <option>Aditi</option>
    </select>
  )
}

// Unsaved-edit state owned by SharedPage, shared with the Split tables.
interface RowEditor {
  pending: Record<number, SharedEdits>
  setPend: (id: number, field: keyof SharedRow, value: unknown) => void
  isDirty: (id: number) => boolean
  saveRow: (row: SharedRow) => void
}

// Payments are settlements between the two, not shared expenses: no shares, never split.
function calcRow(r: SharedRow) {
  const monthly = r.monthly_amount ?? r.amount
  const akhil = r2(monthly * r.share_ratio)
  const aditi = r2(monthly * (1 - r.share_ratio))
  // own = payer's share, owed = the other person's share
  return { base: monthly, own: r.paid_by === 'Akhil' ? akhil : aditi, owed: r.paid_by === 'Akhil' ? aditi : akhil }
}

// One entry per payer, expenses only (settlements excluded). Ignored rows are listed but not summed.
function splitTotals(rows: SharedRow[]) {
  return (['Akhil', 'Aditi'] as const).map(payer => {
    const other = payer === 'Akhil' ? 'Aditi' : 'Akhil'
    const list = rows.filter(r => r.paid_by === payer && !r.is_payment)
    const counted = list.filter(r => !r.is_ignored)
    const sums = counted.reduce(
      (t, r) => { const c = calcRow(r); return { amount: t.amount + c.base, own: t.own + c.own, owed: t.owed + c.owed } },
      { amount: 0, own: 0, owed: 0 },
    )
    return { payer, other, list, count: counted.length, ...sums }
  })
}

function otherOf(p: string) { return p === 'Akhil' ? 'Aditi' : 'Akhil' }

// Top-of-page panel in Split view (replaces the three summary cards). Takes the month's (or FY's)
// rows without the text Filter; the net is the server's closing balance so it always agrees with it.
function SettleUpPanel({ rows, title, periodLabel, carriedFrom, summary }: {
  rows: SharedRow[]; title: string; periodLabel: string; carriedFrom: string; summary?: SharedSummary
}) {
  const [byAkhil, byAditi] = splitTotals(rows)
  const settlements = rows.filter(r => r.is_payment && !r.is_ignored)
  const carried = summary?.carried_over ?? 0
  const net = summary ? summary.net_balance
    : r2(byAkhil.owed - byAditi.owed + settlements.reduce((t, r) => t + settleEffect(r), 0))
  const line = (label: string, who: string, value: string, bold = false) => (
    <div style={{ display: 'flex', gap: 16, fontSize: 14, fontWeight: bold ? 700 : 400 }}>
      <span style={{ flex: '1 1 0' }}>{label}</span>
      <span style={{ flex: '1 1 0' }}>{who}</span>
      <span className="amt" style={{ minWidth: 130 }}>{value}</span>
    </div>
  )
  return (
    <div className="summary-card" style={{ marginBottom: 14 }}>
      <div className="sc-label" style={{ marginBottom: 8 }}>Settle up · {title}</div>
      {carried !== 0 && line(
        `Carried over from ${carriedFrom}`,
        carried > 0 ? 'Aditi owes Akhil' : 'Akhil owes Aditi',
        fmtAmt(Math.abs(carried)),
      )}
      {line(`${periodLabel} shared expenses`, 'Aditi owes Akhil', fmtAmt(byAkhil.owed))}
      {line('', 'Akhil owes Aditi', `−${fmtAmt(byAditi.owed)}`)}
      {settlements.map(r => line(
        `Settlement · ${fmtDate(r.entry_date)}`,
        `${r.paid_by} paid ${otherOf(r.paid_by)}`,
        fmtSigned(settleEffect(r)),
      ))}
      <div style={{
        display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: 16, marginTop: 8, paddingTop: 8,
        borderTop: '1px solid var(--border)', color: net >= 0 ? 'var(--green)' : 'var(--red)',
      }}>
        <span>Net: {net >= 0 ? 'Aditi owes Akhil' : 'Akhil owes Aditi'}</span>
        <span className="amt">{fmtAmt(Math.abs(net))}</span>
      </div>
    </div>
  )
}

// Split view: one collapsible table per payer. Amount/Ratio/Paid By edit like the full table (saved on Update).
function SplitViews({ rows, editor, onIgnore, onDelete }: {
  rows: SharedRow[]
  editor: RowEditor
  onIgnore: (r: SharedRow) => void
  onDelete: (r: SharedRow) => void
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({ Akhil: false, Aditi: false, Settlements: false })
  const tables = splitTotals(rows)
  const settlements = rows.filter(r => r.is_payment)

  return (
    <div style={{ padding: '4px 0 16px' }}>
      {tables.map(t => {
        const isOpen = !!open[t.payer]
        return (
          <div key={t.payer} style={{ marginBottom: 12 }}>
            <div
              onClick={() => setOpen(o => ({ ...o, [t.payer]: !o[t.payer] }))}
              style={{
                display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', padding: '10px 16px', cursor: 'pointer',
                background: 'var(--surface2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)',
                fontSize: 13,
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase', minWidth: 150 }}>
                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Paid by {t.payer}
              </span>
              <span>Total · {t.count} transactions</span>
              <span>Amount: <b className="amt">{fmtAmt(t.amount)}</b></span>
              <span>{t.payer}'s Share: <b className="amt">{fmtAmt(t.own)}</b></span>
              <span>{t.other} Owes: <b className="amt">{fmtAmt(t.owed)}</b></span>
            </div>
            {isOpen && (t.list.length === 0 ? (
              <div className="empty-state" style={{ padding: 16 }}>Nothing paid by {t.payer} in this period</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Merchant</th>
                      <th>Category</th>
                      <th style={{ textAlign: 'right' }}>Amount</th>
                      <th style={{ textAlign: 'right' }}>Mo. Amt</th>
                      <th style={{ textAlign: 'right' }} title="Akhil's share of Mo. Amt">Ratio</th>
                      <th style={{ textAlign: 'right' }}>{t.payer}'s share</th>
                      <th style={{ textAlign: 'right' }}>Owed by {t.other}</th>
                      <th>Paid By</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.list.map(r => {
                      const c = liveCalc(r, editor.pending[r.id])
                      const dirty = editor.isDirty(r.id)
                      return (
                        <tr key={r.id} className={dirty ? 'dirty' : ''} style={{
                          opacity: r.is_ignored ? 0.3 : 1,
                        }}>
                          <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>{fmtDate(r.entry_date)}</td>
                          <td>{r.merchant ?? r.entry_text}</td>
                          <td style={{ color: 'var(--muted)' }}>{r.category ?? '—'}</td>
                          <td style={{ textAlign: 'right' }}>
                            <AmountInput row={r} edits={editor.pending[r.id]} onChange={v => editor.setPend(r.id, 'amount', v)} />
                          </td>
                          <td className="amt"><MonthlyCell row={r} mo={c.mo} /></td>
                          <td style={{ textAlign: 'right' }}>
                            <RatioInput row={r} edits={editor.pending[r.id]} onChange={v => editor.setPend(r.id, 'share_ratio', v)} />
                            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{ratioLabel(c.ratio)}</div>
                          </td>
                          <td className="amt">{fmtAmt(c.own)}</td>
                          <td className="amt" style={{ fontWeight: 600 }}>{fmtAmt(c.owed)}</td>
                          <td><PaidBySelect value={c.paidBy} onChange={v => editor.setPend(r.id, 'paid_by', v)} /></td>
                          <td>
                            <div style={{ display: 'flex', gap: 4 }}>
                              {dirty && (
                                <button className="btn btn-primary btn-sm" onClick={() => editor.saveRow(r)}>Update</button>
                              )}
                              <button
                                className="btn btn-ghost btn-sm"
                                style={{ color: r.is_ignored ? 'var(--muted)' : 'var(--amber)', fontSize: 11 }}
                                onClick={() => onIgnore(r)}
                                title={r.is_ignored ? 'Include in balance' : 'Ignore from balance'}
                              >
                                {r.is_ignored ? 'Include' : 'Ignore'}
                              </button>
                              {!r.history_id && (
                                <button className="btn btn-ghost btn-sm" onClick={() => onDelete(r)}>×</button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                    <tr style={{ fontWeight: 700, borderTop: '2px solid var(--border2)' }}>
                      <td colSpan={3}>Total · {t.count} transactions</td>
                      <td></td>
                      <td className="amt">{fmtAmt(t.amount)}</td>
                      <td></td>
                      <td className="amt">{fmtAmt(t.own)}</td>
                      <td className="amt">{fmtAmt(t.owed)}</td>
                      <td></td>
                      <td></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )
      })}
      {settlements.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div
            onClick={() => setOpen(o => ({ ...o, Settlements: !o.Settlements }))}
            style={{
              display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', padding: '10px 16px', cursor: 'pointer',
              background: 'var(--surface2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)',
              fontSize: 13,
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase', minWidth: 150 }}>
              {open.Settlements ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Settlements
            </span>
            <span>{settlements.length} {settlements.length === 1 ? 'payment' : 'payments'}</span>
            {(['Aditi', 'Akhil'] as const).map(p => {
              const sum = settlements.filter(r => r.paid_by === p && !r.is_ignored).reduce((t, r) => t + r.amount, 0)
              return sum > 0 ? (
                <span key={p}>{p} paid {otherOf(p)} <b className="amt">{fmtAmt(sum)}</b></span>
              ) : null
            })}
          </div>
          {open.Settlements && (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>From → To</th>
                    <th>Note</th>
                    <th style={{ textAlign: 'right' }}>Amount</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {settlements.map(r => (
                    <tr key={r.id} className={editor.isDirty(r.id) ? 'dirty' : ''} style={{ opacity: r.is_ignored ? 0.3 : 1 }}>
                      <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>{fmtDate(r.entry_date)}</td>
                      <td>{r.paid_by} → {otherOf(r.paid_by)}</td>
                      <td style={{ color: 'var(--muted)' }}>{r.entry_text ?? '—'}</td>
                      <td style={{ textAlign: 'right' }}>
                        <AmountInput row={r} edits={editor.pending[r.id]} onChange={v => editor.setPend(r.id, 'amount', v)} />
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {editor.isDirty(r.id) && (
                            <button className="btn btn-primary btn-sm" onClick={() => editor.saveRow(r)}>Update</button>
                          )}
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ color: r.is_ignored ? 'var(--muted)' : 'var(--amber)', fontSize: 11 }}
                            onClick={() => onIgnore(r)}
                            title={r.is_ignored ? 'Include in balance' : 'Ignore from balance'}
                          >
                            {r.is_ignored ? 'Include' : 'Ignore'}
                          </button>
                          {!r.history_id && (
                            <button className="btn btn-ghost btn-sm" onClick={() => onDelete(r)}>×</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Draft row: amount/ratio are null while their field is blank or invalid.
type DraftShared = Omit<CreateSharedPayload, 'monthly_amount' | 'share_ratio'> & { monthly_amount: number | null; share_ratio: number | null }

function AddEntryModal({ onClose, onSave }: { onClose: () => void; onSave: (rows: CreateSharedPayload[]) => void }) {
  const today = new Date().toISOString().slice(0, 10)
  const blank = (): DraftShared => ({
    entry_date: today, merchant: '', category: '', monthly_amount: null, share_ratio: 0.7, paid_by: 'Akhil', owed_by: 'Aditi',
  })
  const [rows, setRows] = useState<DraftShared[]>([blank()])
  const [error, setError] = useState('')

  function update(i: number, k: keyof DraftShared, v: unknown) {
    setRows(prev => prev.map((r, idx) => idx === i ? { ...r, [k]: v } : r))
    setError('')
  }

  function submit() {
    for (const [i, r] of rows.entries()) {
      const where = rows.length > 1 ? `Row ${i + 1}: ` : ''
      if (!r.entry_date) return setError(`${where}Date is required`)
      if (!validNumber('amount', r.monthly_amount)) return setError(where + numberError('Amount', 'amount'))
      if (!validNumber('ratio', r.share_ratio)) return setError(where + numberError('Ratio', 'ratio'))
    }
    onSave(rows.map(r => ({ ...r, monthly_amount: r.monthly_amount as number, share_ratio: r.share_ratio as number })))
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ width: 'min(700px, 97vw)' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          Add Shared Entry
          <button className="btn btn-ghost btn-icon" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="modal-body" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['Date', 'Merchant', 'Category', 'Amount*', 'Ratio', 'Paid By', ''].map(h => (
                  <th key={h} style={{ padding: '4px 6px', fontWeight: 600, color: 'var(--muted)',
                    textAlign: 'left', borderBottom: '1px solid var(--border2)', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="date" className="field-input" style={{ width: 120 }}
                      value={row.entry_date} onChange={e => update(i, 'entry_date', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="text" className="field-input" style={{ width: 110 }}
                      value={row.merchant ?? ''} onChange={e => update(i, 'merchant', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <input type="text" className="field-input" style={{ width: 100 }}
                      value={row.category ?? ''} onChange={e => update(i, 'category', e.target.value)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <NumberInput kind="amount" style={{ width: 90 }}
                      value={row.monthly_amount} onChange={v => update(i, 'monthly_amount', v)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <NumberInput kind="ratio" style={{ width: 60 }} title="Akhil's share, 0 to 1"
                      value={row.share_ratio} onChange={v => update(i, 'share_ratio', v)} />
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <select className="field-input" style={{ width: 80 }}
                      value={row.paid_by} onChange={e => update(i, 'paid_by', e.target.value)}>
                      <option>Akhil</option>
                      <option>Aditi</option>
                    </select>
                  </td>
                  <td style={{ padding: '3px 4px' }}>
                    <button
                      className="btn btn-ghost btn-icon"
                      style={{ color: 'var(--red)', opacity: rows.length === 1 ? 0.3 : 1 }}
                      disabled={rows.length === 1}
                      onClick={() => setRows(prev => prev.filter((_, idx) => idx !== i))}
                    ><X size={13} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn btn-ghost btn-sm" style={{ marginTop: 8 }}
            onClick={() => setRows(prev => [...prev, { ...prev[prev.length - 1] }])}>
            + Add Row
          </button>
          {error && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 8 }}>{error}</div>}
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit}>Add Entries</button>
        </div>
      </div>
    </div>
  )
}

function PaymentModal({ onClose, onSave }: { onClose: () => void; onSave: (p: PaymentPayload) => void }) {
  // amount is null while its field is blank or invalid
  const [form, setForm] = useState<Omit<PaymentPayload, 'amount'> & { amount: number | null }>({
    entry_date: new Date().toISOString().slice(0, 10),
    paid_by: 'Aditi', amount: null,
  })
  function f(k: keyof PaymentPayload, v: unknown) { setForm(p => ({ ...p, [k]: v })) }
  const amountOk = validNumber('amount', form.amount)

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ width: 360 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">Record Payment<button className="btn btn-ghost btn-icon" onClick={onClose}><X size={16} /></button></div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {([['Date*', 'entry_date', 'date'], ['Amount*', 'amount', 'number'], ['Note', 'note', 'text']] as const).map(([label, key, type]) => (
            <div key={key}>
              <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
              {key === 'amount' ? (
                <NumberInput kind="amount" style={{ width: '100%' }} value={form.amount} onChange={v => f('amount', v)} />
              ) : (
                <input type={type} className="field-input" style={{ width: '100%' }}
                  value={form[key] ?? ''}
                  onChange={e => f(key, e.target.value)} />
              )}
            </div>
          ))}
          <div>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Paid By</label>
            <select className="field-input" style={{ width: '100%' }} value={form.paid_by}
              onChange={e => f('paid_by', e.target.value)}>
              <option>Akhil</option>
              <option>Aditi</option>
            </select>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary"
            disabled={!amountOk}
            onClick={() => { if (amountOk) onSave({ ...form, amount: form.amount as number }) }}>Record</button>
        </div>
      </div>
    </div>
  )
}
