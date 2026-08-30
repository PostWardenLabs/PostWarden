import Combobox from './Combobox'
import { matchPreset, PERIOD_PRESETS, rangeForPreset } from './periodPresets'

// Ported from app/static/js/period-picker.js (Phase 4.1) — a convenience
// that fills in the two real date fields a range report actually submits
// (date_from/date_to). Shared by Cash Flow (first caller) and Income
// Statement, per UI_CONSISTENCY_AUDIT.md §4b's own recommendation to
// promote this control to both pages rather than leaving Cash Flow with
// only From/To — the two pages ask the identical "what happened in this
// range" question. Pure preset logic lives in periodPresets.ts, split
// out for oxlint's `react(only-export-components)` rule.
//
// Unlike legacy's own DOM-querying IIFE (which reads/writes #date_from/
// #date_to by id and does its own reverse-match on load to avoid showing
// "Custom range" for a bookmarked "this month" URL), this is a plain
// controlled component: `dateFrom`/`dateTo` are props, not DOM state, so
// React re-renders the right selection from whatever's already in the
// URL — no on-load reverse-match step of its own, `matchPreset` does the
// same computation a render needs anyway.
//
// Legacy's own `combobox.js` progressively enhances every <select> with
// no exceptions (the exact bug class the 2026-08-30 QA pass found and
// fixed across eight instances) — this widget is a Combobox from the
// start rather than a raw <select> for that reason, not style.
interface PeriodPresetPickerProps {
  dateFrom: string
  dateTo: string
  onChange: (dateFrom: string, dateTo: string) => void
}

export default function PeriodPresetPicker({ dateFrom, dateTo, onChange }: PeriodPresetPickerProps) {
  const value = matchPreset(dateFrom, dateTo)
  return (
    <Combobox
      options={PERIOD_PRESETS}
      value={value}
      onChange={(v) => {
        const range = rangeForPreset(v)
        if (range) onChange(range[0], range[1])
      }}
    />
  )
}
