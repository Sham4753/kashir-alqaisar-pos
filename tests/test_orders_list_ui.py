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


def test_counter_cards_and_build_gate_keep_windows_interface_current():
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "pos-modern.css").read_text(encoding="utf-8")
    build = (ROOT / "Setup_CAESAR_OneFile.ps1").read_text(encoding="utf-8")
    for counter_id in ("counterOrders", "counterReady", "counterSales"):
        assert f'id="{counter_id}"' in html
        assert counter_id in build
    assert "/api/dashboard/counters" in html
    assert ".counter-strip { display: grid !important;" in css
    assert "refusing to build an incomplete interface" in build
    assert 'Get-ChildItem -LiteralPath $ProductDir -Filter "index.html"' in build
    assert "Built package contains all three visible POS counter cards." in build


def test_manager_can_hard_delete_order_or_clean_sales_but_not_debt_receipts():
    source = ORDERS_PAGE.read_text(encoding="utf-8")
    backend = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    assert 'data-order-action="delete-order"' in source
    assert "hardDeleteOrder(orderId)" in source
    assert "DELETE_ALL_TEST_ORDERS" in source
    assert "اكتب رقم الفاتورة كما هو" in source
    assert "orderMaintenance').hidden = currentRole !== 'manager'" in source
    assert "@app.route('/api/orders/<order_id>', methods=['DELETE'])" in backend
    assert "@app.route('/api/orders', methods=['DELETE'])" in backend
    assert "_is_debt_receipt_order(order)" in backend
    assert "_save_pre_cleanup_order_backup" in backend


def test_embedded_windows_cffi_repair_wheels_are_available():
    wheelhouse = ROOT / "offline_wheels"
    wheels = {path.name for path in wheelhouse.glob("*.whl")}
    assert "cffi-2.1.1-cp312-cp312-win_amd64.whl" in wheels
    assert "pycparser-3.0-py3-none-any.whl" in wheels
    assert (wheelhouse / "SHA256SUMS.txt").is_file()
