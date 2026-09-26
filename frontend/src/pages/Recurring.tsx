import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Play, X } from 'lucide-react'
import { Layout } from '../components/Layout'
import { NumberInput, validNumber, numberError } from '../components/NumberInput'
import { useToast } from '../hooks/useToast'
import { recurringApi, type RecurringPayload } from '../api/recurring'
import type { RecurringDef, Cadence, SpendType } from '../types'

const CADENCE_OPTS = ['O', 'M', 'Q', 'A']
const SPEND_OPTS: SpendType[] = ['Expense', 'Investment', 'Saving']

function fmtAmount(n: number) {
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2 })
}

// Form state: numeric fields are null while their field is blank or invalid.
type RecurringForm = Omit<RecurringPayload, 'amount' | 'divide_by' | 'share_ratio' | 'day_of_month'> & {
  amount: number | null; divide_by: number | null; share_ratio: number | null; day_of_month: number | null
}

const BLANK: RecurringForm = {
  entry_text: '', merchant: '', amount: null, category: '', sub_category: '',
  spend_type: 'Expense', cadence: 'M', divide_by: 1,
  shared_expense: 'N', share_ratio: 1.0, active: true,
  day_of_month: 1, paid_by: 'Akhil', start_this_month: false,
}

export function RecurringPage() {
  const qc = useQueryClient()
  const { toast } = useToast()

  const { data: defs = [], isLoading } = useQuery({
    queryKey: ['recurring'],
    queryFn: recurringApi.list,
  })

  const [modal, setModal] = useState<{ open: boolean; editing: RecurringDef | null }>({
    open: false, editing: null,
  })
  const [form, setForm] = useState<RecurringForm>(BLANK)

  const createMut = useMutation({
    mutationFn: recurringApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); closeModal(); toast('Definition created', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: RecurringPayload }) =>
      recurringApi.update(id, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); closeModal(); toast('Updated', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: recurringApi.delete,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['recurring'] }); toast('Deleted', 'success') },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const generateMut = useMutation({
    mutationFn: () => recurringApi.generate(),
    onSuccess: (r) => toast(`Generated ${r.count} entries`, 'success'),
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function openAdd()              { setForm(BLANK);   setModal({ open: true, editing: null }) }
  function openEdit(d: RecurringDef) {
    setForm({
      entry_text: d.entry_text, merchant: d.merchant ?? '', amount: d.amount,
      category: d.category ?? '', sub_category: d.sub_category ?? '',
      spend_type: (d.spend_type ?? 'Expense') as SpendType,
      cadence: d.cadence, divide_by: d.divide_by,
      shared_expense: d.shared_expense, share_ratio: d.share_ratio, active: d.active,
      day_of_month: d.day_of_month, paid_by: d.paid_by,
    })
    setModal({ open: true, editing: d })
  }
  function closeModal() { setModal({ open: false, editing: null }) }

  function f(k: keyof RecurringForm, v: unknown) { setForm(p => ({ ...p, [k]: v })) }

  function save() {
    if (!form.entry_text.trim()) { toast('Description is required', 'error'); return }
    if (!validNumber('amount', form.amount)) { toast(numberError('Amount', 'amount'), 'error'); return }
    if (!validNumber('divisor', form.divide_by)) { toast(numberError('Divide By', 'divisor'), 'error'); return }
    if (!validNumber('divisor', form.day_of_month) || form.day_of_month > 31) {
      toast('Debit day must be a whole number from 1 to 31', 'error'); return
    }
    if (form.shared_expense === 'Y' && !validNumber('ratio', form.share_ratio)) {
      toast(numberError('Share Ratio', 'ratio'), 'error'); return
    }
    const payload: RecurringPayload = {
      ...form, amount: form.amount, divide_by: form.divide_by, share_ratio: form.share_ratio ?? 1.0,
      day_of_month: form.day_of_month,
    }
    if (modal.editing) {
      updateMut.mutate({ id: modal.editing.id, payload })
    } else {
      createMut.mutate(payload)
    }
  }

  async function toggleActive(d: RecurringDef) {
    await recurringApi.update(d.id, {
      entry_text: d.entry_text, merchant: d.merchant ?? '', amount: d.amount,
      category: d.category ?? '', sub_category: d.sub_category ?? '',
      spend_type: (d.spend_type ?? 'Expense') as SpendType,
      cadence: d.cadence, divide_by: d.divide_by,
      shared_expense: d.shared_expense, share_ratio: d.share_ratio, active: !d.active,
      day_of_month: d.day_of_month, paid_by: d.paid_by,
    })
    qc.invalidateQueries({ queryKey: ['recurring'] })
  }

  const active = defs.filter(d => d.active).length
  const monthly = defs.filter(d => d.active).reduce((s, d) => s + d.amount / d.divide_by, 0)
  const lastGen = defs.reduce<string | null>((latest, d) => {
    if (!d.last_generated) return latest
    return !latest || d.last_generated > latest ? d.last_generated : latest
  }, null)

  const monthlyPreview = form.amount ? form.amount / (form.divide_by || 1) : 0   // blank fields preview as 0 / ÷1
  const finalPreview   = form.shared_expense === 'Y'
    ? monthlyPreview * (form.share_ratio ?? 1)
    : monthlyPreview

  const headerExtra = (
    <button
      className="btn btn-primary btn-sm"
      onClick={() => generateMut.mutate()}
      disabled={generateMut.isPending}
    >
      <Play size={13} /> {generateMut.isPending ? 'Generating…' : 'Generate Now'}
    </button>
  )

  return (
    <Layout headerExtra={headerExtra}>
      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Total Definitions', value: defs.length },
          { label: 'Active',            value: active },
          { label: 'Est. Monthly',      value: fmtAmount(monthly) },
          { label: 'Last Generated',    value: lastGen ?? '—' },
        ].map(s => (
          <div key={s.label} className="card" style={{ flex: 1, padding: '12px 14px' }}>
            <div className="sc-label">{s.label}</div>
            <div className="sc-value" style={{ fontSize: 18 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Table card */}
      <div className="card">
        <div className="card-header">
          Recurring Definitions
          <button className="btn btn-primary btn-sm" onClick={openAdd}>
            <Plus size={13} /> Add
          </button>
        </div>
        {isLoading ? (
          <div className="empty-state">Loading…</div>
        ) : defs.length === 0 ? (
          <div className="empty-state">No recurring definitions yet</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Category</th>
                  <th>Amount</th>
                  <th>Monthly</th>
                  <th title="Debit day; the entry is dated this day">Day</th>
                  <th>Cadence</th>
                  <th>Shared</th>
                  <th>Active</th>
                  <th>Last Gen</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {defs.map(d => (
                  <tr key={d.id} style={{ opacity: d.active ? 1 : 0.45 }}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{d.entry_text}</div>
                      {d.merchant && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.merchant}</div>}
                    </td>
                    <td>
                      <div>{d.category}</div>
                      {d.sub_category && <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.sub_category}</div>}
                    </td>
                    <td>{fmtAmount(d.amount)}</td>
                    <td>{fmtAmount(d.amount / d.divide_by)}</td>
                    <td>{d.day_of_month}</td>
                    <td>
                      <span className="pill" style={{
                        background: 'var(--surface2)', color: 'var(--muted)',
                      }}>{d.cadence}</span>
                    </td>
                    <td>
                      {d.shared_expense === 'Y' ? (
                        <>
                          <div>{Math.round(d.share_ratio * 100)}%</div>
                          <div style={{ fontSize: 11, color: 'var(--muted)' }}>paid by {d.paid_by}</div>
                        </>
                      ) : '—'}
                    </td>
                    <td>
                      <input
                        type="checkbox" className="active-toggle" checked={d.active}
                        onChange={() => toggleActive(d)}
                      />
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                      {d.last_generated ?? (d.start_month ? `Starts ${monthName(d.start_month)}` : '—')}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(d)}>Edit</button>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            if (confirm('Delete this definition?')) deleteMut.mutate(d.id)
                          }}
                        >Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal */}
      {modal.open && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal-box" style={{ width: 'min(560px, 95vw)' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              {modal.editing ? 'Edit Definition' : 'Add Definition'}
              <button className="btn btn-ghost btn-icon" onClick={closeModal}><X size={16} /></button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 14px' }}>
                {([
                  ['Description*', 'entry_text', 'text'],
                  ['Merchant',     'merchant',   'text'],
                ] as const).map(([label, key, type]) => (
                  <div key={key} style={{ gridColumn: key === 'entry_text' ? '1 / -1' : undefined }}>
                    <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>{label}</label>
                    <input
                      type={type} className="field-input" style={{ width: '100%' }}
                      value={form[key] as string}
                      onChange={e => f(key, e.target.value)}
                    />
                  </div>
                ))}

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Amount*</label>
                  <NumberInput kind="amount" style={{ width: '100%' }}
                    value={form.amount} onChange={v => f('amount', v)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Cadence</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.cadence}
                    onChange={e => f('cadence', e.target.value as Cadence)}>
                    {CADENCE_OPTS.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Category</label>
                  <input type="text" className="field-input" style={{ width: '100%' }}
                    value={form.category} onChange={e => f('category', e.target.value)} />
                </div>
                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Subcategory</label>
                  <input type="text" className="field-input" style={{ width: '100%' }}
                    value={form.sub_category} onChange={e => f('sub_category', e.target.value)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Spend Type</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.spend_type}
                    onChange={e => f('spend_type', e.target.value as SpendType)}>
                    {SPEND_OPTS.map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Divide By</label>
                  <NumberInput kind="divisor" style={{ width: '100%' }}
                    value={form.divide_by} onChange={v => f('divide_by', v)} />
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Debit day</label>
                  <NumberInput kind="divisor" style={{ width: '100%' }} title="1-31; 31 = last day of shorter months"
                    value={form.day_of_month} onChange={v => f('day_of_month', v)} />
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>31 = last day of shorter months</div>
                </div>

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Shared</label>
                  <select className="field-input" style={{ width: '100%' }}
                    value={form.shared_expense}
                    onChange={e => f('shared_expense', e.target.value as 'Y' | 'N')}>
                    <option value="N">No</option>
                    <option value="Y">Yes</option>
                  </select>
                </div>

                {form.shared_expense === 'Y' && (
                  <div>
                    <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Share Ratio</label>
                    <NumberInput kind="ratio" style={{ width: '100%' }} title="Akhil's share, 0 to 1"
                      value={form.share_ratio} onChange={v => f('share_ratio', v)} />
                  </div>
                )}

                {form.shared_expense === 'Y' && (
                  <div>
                    <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Paid by</label>
                    <select className="field-input" style={{ width: '100%' }}
                      value={form.paid_by} onChange={e => f('paid_by', e.target.value)}>
                      <option>Akhil</option>
                      <option>Aditi</option>
                    </select>
                  </div>
                )}

                {!modal.editing && (
                  <div style={{ gridColumn: '1 / -1' }}>
                    <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                      <input type="checkbox" checked={!!form.start_this_month}
                        onChange={e => f('start_this_month', e.target.checked)}
                        style={{ accentColor: 'var(--teal)' }} />
                      Start this month
                      <span style={{ color: 'var(--muted)' }}>→ first entry: {firstEntryLabel(form)}</span>
                    </label>
                  </div>
                )}

                <div>
                  <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Active</label>
                  <input type="checkbox" checked={form.active}
                    onChange={e => f('active', e.target.checked)}
                    style={{ width: 16, height: 16, cursor: 'pointer', accentColor: 'var(--teal)' }} />
                </div>
              </div>

              {/* Preview */}
              <div style={{ marginTop: 14, padding: '10px 12px', background: 'var(--surface2)',
                borderRadius: 'var(--radius-sm)', fontSize: 12, color: 'var(--muted)', display: 'flex', gap: 20 }}>
                <span>Monthly: <strong style={{ color: 'var(--text)' }}>{fmtAmount(monthlyPreview)}</strong></span>
                <span>Final: <strong style={{ color: 'var(--teal)' }}>{fmtAmount(finalPreview)}</strong></span>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={closeModal}>Cancel</button>
              <button
                className="btn btn-primary"
                onClick={save}
                disabled={createMut.isPending || updateMut.isPending}
              >
                {createMut.isPending || updateMut.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  )
}

function monthName(iso: string) {
  return new Date(`${iso.slice(0, 7)}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
}

// Date of a new item's first entry: its debit day (clamped to the month's length) in this month when
// "Start this month" is ticked, otherwise next month. Mirrors db.recurring_effective_day.
function firstEntryLabel(form: { day_of_month: number | null; start_this_month?: boolean }) {
  const now = new Date()
  const first = new Date(now.getFullYear(), now.getMonth() + (form.start_this_month ? 0 : 1), 1)
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  const day = Math.min(Math.max(1, form.day_of_month ?? 1), last)
  const d = new Date(first.getFullYear(), first.getMonth(), day)
  const label = d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  return form.start_this_month && day <= now.getDate() ? `${label} (added tonight)` : label
}
