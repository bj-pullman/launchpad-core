from __future__ import annotations

from typing import Any


TRANSACTION_CODE_REGISTRY: dict[str, dict[str, Any]] = {
    "11": {
        "label": "Post Expenditure Budgets",
        "ledger_kind": "budget",
        "effect": "budget_original",
        "description": "Posts original expenditure budget amounts to budget accounts.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
    "13": {
        "label": "Adjust Expenditure Budgets",
        "ledger_kind": "budget",
        "effect": "budget_adjustment",
        "description": "Adjusts expenditure budget amounts on budget accounts.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
    "17": {
        "label": "Add Encumbrances",
        "ledger_kind": "encumbrance",
        "effect": "encumbrance_add",
        "description": "Adds purchase order encumbrance activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": True,
        "affects_actual_spend": False,
    },
    "18": {
        "label": "Change Encumbrances",
        "ledger_kind": "encumbrance",
        "effect": "encumbrance_change",
        "description": "Changes purchase order encumbrance activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": True,
        "affects_actual_spend": False,
    },
    "19": {
        "label": "Journal Entries",
        "ledger_kind": "journal",
        "effect": "journal_entry",
        "description": "Posts journal entry activity. These rows are preserved in the ledger for review.",
        "affects_budget_accounts": False,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
    "20": {
        "label": "Accounts Payable Manual/Void Checks",
        "ledger_kind": "expenditure",
        "effect": "ap_manual_or_void",
        "description": "Posts manual or voided AP check activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": True,
        "affects_actual_spend": True,
    },
    "21": {
        "label": "Accounts Payable",
        "ledger_kind": "expenditure",
        "effect": "ap_payment",
        "description": "Posts AP payment activity and actual expenditures.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": True,
        "affects_actual_spend": True,
    },
    "22": {
        "label": "Payroll Interface and Manual Payroll",
        "ledger_kind": "payroll",
        "effect": "payroll",
        "description": "Posts payroll-related ledger activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": False,
        "affects_actual_spend": True,
    },
    "24": {
        "label": "Receipts / Deposits",
        "ledger_kind": "receipt",
        "effect": "receipt",
        "description": "Posts receipt or deposit activity.",
        "affects_budget_accounts": False,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
    "25": {
        "label": "Expenditure Budget Transfer",
        "ledger_kind": "budget",
        "effect": "budget_transfer",
        "description": "Posts expenditure budget transfer activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
    "27": {
        "label": "Project Budget Transfer",
        "ledger_kind": "budget",
        "effect": "project_budget_transfer",
        "description": "Posts project budget transfer activity.",
        "affects_budget_accounts": True,
        "affects_purchase_orders": False,
        "affects_actual_spend": False,
    },
}


def normalize_transaction_code(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return value.split("-", 1)[0].strip()


def get_transaction_code_info(value: Any) -> dict[str, Any]:
    code = normalize_transaction_code(value)
    if not code:
        return {
            "code": None,
            "label": "Unmapped",
            "ledger_kind": "other",
            "effect": "unknown",
            "description": "No transaction code was provided.",
            "affects_budget_accounts": False,
            "affects_purchase_orders": False,
            "affects_actual_spend": False,
            "is_known": False,
        }

    info = TRANSACTION_CODE_REGISTRY.get(code)
    if not info:
        return {
            "code": code,
            "label": "Unknown Transaction Code",
            "ledger_kind": "other",
            "effect": "unknown",
            "description": "This transaction code is not in the registry yet and should be reviewed.",
            "affects_budget_accounts": False,
            "affects_purchase_orders": False,
            "affects_actual_spend": False,
            "is_known": False,
        }

    return {"code": code, "is_known": True, **info}


def list_transaction_codes() -> list[dict[str, Any]]:
    return [get_transaction_code_info(code) for code in sorted(TRANSACTION_CODE_REGISTRY.keys(), key=int)]
