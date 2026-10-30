"""Central RBAC policy for CAESAR POS.

The policy is deliberately kept independent from Flask request/session handling so
that it can be reviewed, tested, and reused by the desktop and LAN clients.
"""
from __future__ import annotations

import re

ROLE_LABELS = {
    "cashier": "كاشير قيصر",
    "waiter": "نادل",
    "supervisor": "مشرف",
    "manager": "مدير",
}
ALL_ROLES = frozenset(ROLE_LABELS)
OPERATIONAL_ROLES = frozenset({"cashier", "supervisor", "manager"})
MANAGEMENT_ROLES = frozenset({"supervisor", "manager"})
MANAGER_ONLY = frozenset({"manager"})

ROLE_PAGE_ACCESS = {
    "index.html": set(OPERATIONAL_ROLES),
    "orders_list.html": set(OPERATIONAL_ROLES),
    "kitchen.html": set(OPERATIONAL_ROLES),
    "tables.html": set(OPERATIONAL_ROLES),
    "customers.html": set(OPERATIONAL_ROLES),
    "delivery.html": set(OPERATIONAL_ROLES),
    "waiting_screen.html": set(OPERATIONAL_ROLES),
    "daily_guide.html": set(OPERATIONAL_ROLES),
    "attendance.html": set(OPERATIONAL_ROLES),
    "dashboard.html": set(MANAGEMENT_ROLES),
    "debts.html": set(MANAGEMENT_ROLES),
    "settings.html": set(MANAGER_ONLY),
    "printer_settings.html": set(MANAGER_ONLY),
    "menu_manager.html": set(MANAGER_ONLY),
    "employees.html": set(MANAGER_ONLY),
    "raw_materials.html": set(MANAGEMENT_ROLES),
    "analytics.html": set(MANAGER_ONLY),
    "manager_ops.html": set(MANAGER_ONLY),
    "expenses.html": set(MANAGER_ONLY),
    "shift.html": set(OPERATIONAL_ROLES),
    "mobile.html": set(OPERATIONAL_ROLES),
}

PUBLIC_API_PATHS = {
    "/api/setup/status",
    "/api/setup/initialize",
    "/api/network/info",
    "/api/restaurant/name",
    "/api/restaurant/identity",
    "/api/settings/support-info",
    "/api/settings/users",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/verify",
    "/api/auth/lock",
    "/api/auth/unlock",
}

CASHIER_READ_PREFIXES = (
    "/api/menu",
    "/api/barcode/",
    "/api/settings/currency",
    "/api/restaurant/name",
    "/api/inventory/alerts",
    "/api/employees",
    "/api/materials",
    "/api/suppliers",
    "/api/printer/settings",
    "/api/kitchen/orders",
    "/api/tables",
    "/api/dine-in/",
    "/api/shifts/current",
    "/api/shift/users",
    "/api/orders",
    "/api/order/",
    "/api/customers",
    "/api/ready-orders",
    "/api/delivery/orders",
    "/api/dashboard/counters",
    "/api/sync/status",
    "/api/settings/features",
)

DAILY_OPERATION_WRITE_PATTERNS = (
    r"/api/orders",
    r"/api/orders/[^/]+/(?:void|split|edit-items)",
    r"/api/printer/orders/[^/]+/retry",
    r"/api/dine-in/sessions(?:/[^/]+)?(?:/(?:move|close))?",
    r"/api/kitchen/orders/[^/]+/status",
    r"/api/delivery/orders/[^/]+",
    r"/api/loyalty/redeem",
    r"/api/customers",
)

# Specific policies are documented here; any route not matched below falls back
# to the conservative method rule in ``allowed_roles_for_request``.
ROUTE_POLICIES = (
    ("GET", "/api/dashboard/counters", OPERATIONAL_ROLES),
    ("GET", "/api/menu", OPERATIONAL_ROLES),
    ("GET", "/api/orders", OPERATIONAL_ROLES),
    ("GET", "/api/kitchen/orders", OPERATIONAL_ROLES),
    ("GET", "/api/ready-orders", OPERATIONAL_ROLES),
    ("GET", "/api/delivery/orders", OPERATIONAL_ROLES),
    ("GET", "/api/customers", OPERATIONAL_ROLES),
    ("GET", "/api/inventory/alerts", OPERATIONAL_ROLES),
    ("GET", "/api/employees", MANAGER_ONLY),
    ("POST", "/api/employees", MANAGER_ONLY),
    ("PUT", "/api/employees/<eid>", MANAGER_ONLY),
    ("DELETE", "/api/employees/<eid>", MANAGER_ONLY),
    ("POST", "/api/employees/<eid>/pay-salary", MANAGER_ONLY),
    ("POST", "/api/employees/<eid>/advance", MANAGER_ONLY),
    ("GET", "/api/shift/users", OPERATIONAL_ROLES),
    ("GET", "/api/shifts", OPERATIONAL_ROLES),
    ("GET", "/api/shifts/cashiers", OPERATIONAL_ROLES),
    ("POST", "/api/shifts/handover", OPERATIONAL_ROLES),
    ("POST", "/api/shifts/reset-counter", MANAGER_ONLY),
    ("POST", "/api/orders/archive", MANAGER_ONLY),
    ("POST", "/api/orders/<order_id>/void", MANAGER_ONLY),
    ("DELETE", "/api/orders", MANAGER_ONLY),
    ("DELETE", "/api/orders/<order_id>", MANAGER_ONLY),
    ("GET", "/api/debts", MANAGEMENT_ROLES),
    ("POST", "/api/debts", MANAGEMENT_ROLES),
    ("PUT", "/api/debts/<did>", MANAGEMENT_ROLES),
    ("POST", "/api/debts/<did>/pay", MANAGEMENT_ROLES),
    ("DELETE", "/api/debts/<did>", MANAGEMENT_ROLES),
    ("GET", "/api/attendance", OPERATIONAL_ROLES),
    ("POST", "/api/attendance/clock", OPERATIONAL_ROLES),
    ("GET", "/api/materials", MANAGEMENT_ROLES),
    ("POST", "/api/materials", MANAGER_ONLY),
    ("PUT", "/api/materials/<mid>", MANAGER_ONLY),
    ("DELETE", "/api/materials/<mid>", MANAGER_ONLY),
    ("GET", "/api/suppliers", OPERATIONAL_ROLES),
    ("GET", "/api/suppliers/<sid>/payments", MANAGEMENT_ROLES),
    ("POST", "/api/suppliers/<sid>/payments", MANAGER_ONLY),
    ("GET", "/api/expenses", MANAGER_ONLY),
    ("POST", "/api/expenses", MANAGER_ONLY),
    ("DELETE", "/api/expenses/<eid>", MANAGER_ONLY),
    ("POST", "/api/orders", OPERATIONAL_ROLES),
    # يستطيع المستخدم التشغيلي طلب تعديل الأصناف، لكن الخادم لا ينفذه إلا
    # بعد check_manager_password الذي يثبت كلمة مرور مدير فعلي.
    ("POST", "/api/orders/<order_id>/edit-items", OPERATIONAL_ROLES),
    ("GET", "/api/held-orders", OPERATIONAL_ROLES),
    ("POST", "/api/held-orders", OPERATIONAL_ROLES),
    ("DELETE", "/api/held-orders/<hold_id>", OPERATIONAL_ROLES),
    ("POST", "/api/kitchen/orders/<order_id>/status", OPERATIONAL_ROLES),
    ("POST", "/api/dine-in/sessions", OPERATIONAL_ROLES),
    ("POST", "/api/dine-in/sessions/<session_id>/close", OPERATIONAL_ROLES),
    ("POST", "/api/delivery/orders/<order_id>", OPERATIONAL_ROLES),
    ("POST", "/api/customers", OPERATIONAL_ROLES),
)


def is_daily_operational_write(path: str) -> bool:
    """Return whether a write changes a normal day-to-day operation."""
    return any(re.fullmatch(pattern, path) for pattern in DAILY_OPERATION_WRITE_PATTERNS)


def _matches_policy(pattern: str, path: str) -> bool:
    expression = re.sub(r"<[^>]+>", r"[^/]+", pattern)
    return re.fullmatch(expression, path) is not None


def allowed_roles_for_request(method: str, path: str) -> frozenset[str] | None:
    """Return the centralized allow-list for an API request."""
    if path in PUBLIC_API_PATHS and not (path == "/api/settings/users" and method.upper() != "GET"):
        return ALL_ROLES
    for policy_method, pattern, roles in ROUTE_POLICIES:
        if method.upper() == policy_method and _matches_policy(pattern, path):
            return frozenset(roles)
    if method.upper() in {"POST", "PUT", "DELETE", "PATCH"} and is_daily_operational_write(path):
        return OPERATIONAL_ROLES
    if method.upper() == "GET" and path.startswith(CASHIER_READ_PREFIXES):
        return OPERATIONAL_ROLES
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return MANAGEMENT_ROLES
    return MANAGER_ONLY


def role_can_access(method: str, path: str, role: str | None) -> bool:
    allowed = allowed_roles_for_request(method, path)
    return bool(role and allowed and role in allowed)


def page_allowed(filename: str, role: str | None) -> bool:
    return bool(role and role in ROLE_PAGE_ACCESS.get(filename, MANAGER_ONLY))
