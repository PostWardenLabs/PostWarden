import Combobox from './Combobox'
import { matchPreset, PERIOD_PRESETS, rangeForPreset } from './periodPresets'

// A convenience that fills in the two real date fields a range report
// actually submits (date_from/date_to). Shared by Cash Flow (first
// caller) and Income Statement, per the UI-consistency audit's own
// recommendation to promote this control to both pages rather than
// leaving Cash Flow with only From/To — the two pages ask the identical
// "what happened in this range" question. Pure preset logic lives in
// periodPresets.ts, split out for oxlint's `react(only-export-components)`
// rule.
//
// A plain controlled component: `dateFrom`/`dateTo` are props, not DOM
// state, so React re-renders the right selection from whatever's already
// in the URL — `matchPreset` does the reverse-match computation a render
// needs.
//
// Built as a Combobox from the start, not a raw <select> — the
// 2026-08-30 QA pass found and fixed the same "raw <select> missing its
// enhancement" bug class across eight other instances in this app.
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
