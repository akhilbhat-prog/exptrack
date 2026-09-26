interface Props {
  title: string
  message: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ title, message, confirmLabel = 'Confirm', onConfirm, onCancel }: Props) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" style={{ width: 380 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">{title}</div>
        <div className="modal-body" style={{ padding: '16px 18px', fontSize: 14 }}>
          {message}
        </div>
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-danger" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}
