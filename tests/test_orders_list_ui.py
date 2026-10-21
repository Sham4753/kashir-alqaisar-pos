from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORDERS_PAGE = ROOT / "app" / "orders_list.html"


def test_order_actions_use_delegated_data_attributes_not_out_of_scope_row_vars():
    source = ORDERS_PAGE.read_text(encoding="utf-8")
    assert 'data-order-action="void-order"' in source
    assert 'data-order-action="edit-item"' in source
    assert "button[data-order-action]" in source
    assert "voidOrder(orderId)" in source
    assert "currentRole === 'manager'" in source
    assert "إلغاء الطلب متاح للمدير فقط" in source
    assert 'onclick="voidOrder(jsArg(o.id))"' not in source
    assert 'onclick="editOrderItem(jsArg(o.id)' not in source


def test_cancel_confirmation_keeps_audit_and_manager_session_approval():
    source = ORDERS_PAGE.read_text(encoding="utf-8")
    assert "getManagerCreds(true)" in source
    assert "payload.manager_approval" in source
    assert "سجل التدقيق" in source


def test_cancel_refreshes_operational_list_and_bypasses_browser_cache():
    source = ORDERS_PAGE.read_text(encoding="utf-8")
    assert "cache: 'no-store'" in source
    assert "allOrders = allOrders.filter(order => String(order.id) !== String(orderId))" in source
    assert "await loadOrders()" in source


def test_dashboard_counters_use_today_orders_for_cashier_view():
    source = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert "today_orders = _today_orders(data)" in source
    assert "active_orders = today_orders" in source
