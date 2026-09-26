import { useState, useEffect } from 'react'

// amount: > 0 · ratio: 0..1 inclusive (0 = the whole expense is Aditi's) · divisor: whole number >= 1
export type NumberKind = 'amount' | 'ratio' | 'divisor'

const PATTERN: Record<NumberKind, RegExp> = {
  amount:  /^\d*\.?\d*$/,
  ratio:   /^\d*\.?\d*$/,
  divisor: /^\d+$/,
}

export function validNumber(kind: NumberKind, v: number | null | undefined): v is number {
  if (v == null || !Number.isFinite(v)) return false
  switch (kind) {
    case 'amount':  return v > 0
    case 'ratio':   return v >= 0 && v <= 1
    case 'divisor': return Number.isInteger(v) && v >= 1
  }
}

export function numberError(label: string, kind: NumberKind): string {
  switch (kind) {
    case 'amount':  return `${label} must be more than 0`
    case 'ratio':   return `${label} must be between 0 and 1`
    case 'divisor': return `${label} must be a whole number of 1 or more`
  }
}

function parse(kind: NumberKind, text: string): number | null {
  const t = text.trim()
  if (!t || !PATTERN[kind].test(t) || t === '.') return null
  const v = Number(t)
  return validNumber(kind, v) ? v : null
}

interface Props {
  value:        number | null
  onChange:     (v: number | null) => void   // null while the field is blank or invalid
  kind:         NumberKind
  revertOnBlur?: boolean                      // auto-save screens: leaving a blank/invalid field restores `value`
  className?:   string
  style?:       React.CSSProperties
  disabled?:    boolean
  title?:       string
  placeholder?: string
}

// Numeric text field that can be cleared and retyped: blank stays blank (no snapping to a default),
// out-of-range text is highlighted, and the parent only ever receives a valid number or null.
export function NumberInput({ value, onChange, kind, revertOnBlur, className, style, disabled, title, placeholder }: Props) {
  const [text, setText] = useState(value == null ? '' : String(value))

  // Follow value changes made outside this field (save, reset, a toggle setting a default).
  useEffect(() => {
    setText(t => (parse(kind, t) === value ? t : value == null ? '' : String(value)))
  }, [value, kind])

  const invalid = text.trim() !== '' && parse(kind, text) === null
  return (
    <input
      type="text"
      inputMode={kind === 'divisor' ? 'numeric' : 'decimal'}
      className={`${className ?? 'field-input'}${invalid ? ' invalid' : ''}`}
      style={style} disabled={disabled} placeholder={placeholder}
      title={invalid ? numberError('Value', kind) : title}
      value={text}
      onChange={e => { setText(e.target.value); onChange(parse(kind, e.target.value)) }}
      onBlur={() => {
        if (revertOnBlur && parse(kind, text) === null) setText(value == null ? '' : String(value))
      }}
    />
  )
}
