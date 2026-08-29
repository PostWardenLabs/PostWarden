"""Shared CSV/XLSX writers, consumed by entries, reports, and imports alike.

XLSX output carries live Excel formulas (cell-by-cell sums, not ranges) —
see REBUILD.md §6/§7 on why that's deliberate. Lands in Phase 1.12.
"""
