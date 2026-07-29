from __future__ import annotations

from typing import Any

from crs_fatca_generator.models.mapping import GroupingRules


class GroupingService:
    def group_by_account(self, rows: list[dict[str, Any]], rules: GroupingRules) -> dict[str, list[dict[str, Any]]]:
        key_col = rules.account_key
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get(key_col) or row.get("_excel_row") or "")
            groups.setdefault(key, []).append(row)
        return groups
