import { useRef, type InputHTMLAttributes } from 'react'

interface NumberStepperProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange' | 'value'> {
  value: string
  onChange: (value: string) => void
}

// Ported from app/static/number-stepper.js — custom up/down chevrons over
// a plain <input type="number">, replacing the browser's own spinner
// arrows so a native OS control doesn't sit inside an otherwise hand-
// styled page. Typing directly and the keyboard's own Up/Down arrows
// still work unchanged; the input stays a real type="number" throughout.
//
// A controlled component here (value/onChange props), unlike legacy's
// plain DOM enhancement of a server-rendered field — but the step logic
// itself still goes through the native input's own .stepUp()/.stepDown()
// via a ref rather than reimplementing step/min/max arithmetic by hand,
// so the browser's own validation semantics (respecting `step` alignment,
// clamping to `min`/`max`) stay authoritative. onChange fires only when
// the native call actually changed the value, same as legacy dispatching
// input/change events only on an actual change.
export default function NumberStepper({
  value,
  onChange,
  min,
  max,
  step,
  disabled,
  className,
  ...rest
}: NumberStepperProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  function stepBy(dir: 1 | -1) {
    const input = inputRef.current
    if (!input) return
    const before = input.value
    try {
      if (dir > 0) input.stepUp()
      else input.stepDown()
    } catch {
      // stepUp/stepDown throw if the result would land outside min/max
      // (even by a fraction of `step`) — fall back to a plain arithmetic
      // nudge, clamped to bounds, same fallback number-stepper.js uses.
      const s = Number(step) || 1
      const lo = min !== undefined && min !== '' ? Number(min) : -Infinity
      const hi = max !== undefined && max !== '' ? Number(max) : Infinity
      const cur = Number(input.value) || 0
      input.value = String(Math.min(hi, Math.max(lo, cur + dir * s)))
    }
    if (input.value !== before) onChange(input.value)
  }

  const cur = value === '' ? null : Number(value)
  const hi = max !== undefined && max !== '' ? Number(max) : null
  const lo = min !== undefined && min !== '' ? Number(min) : null
  const upDisabled = !!disabled || (cur !== null && hi !== null && cur >= hi)
  const downDisabled = !!disabled || (cur !== null && lo !== null && cur <= lo)

  return (
    <span className="number-stepper">
      <input
        {...rest}
        ref={inputRef}
        type="number"
        className={['number-input', className].filter(Boolean).join(' ')}
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        className="number-step step-up"
        aria-label="Increase"
        tabIndex={-1}
        disabled={upDisabled}
        onClick={() => stepBy(1)}
      >
        <span className="chevron chevron-up" />
      </button>
      <button
        type="button"
        className="number-step step-down"
        aria-label="Decrease"
        tabIndex={-1}
        disabled={downDisabled}
        onClick={() => stepBy(-1)}
      >
        <span className="chevron chevron-down" />
      </button>
    </span>
  )
}
