import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
CSS = (APP / 'pos-modern.css').read_text(encoding='utf-8')
HTML = (APP / 'index.html').read_text(encoding='utf-8')


class PosLayoutTests(unittest.TestCase):
    def test_desktop_uses_catalog_and_compact_cart_columns(self):
        rules = re.findall(r'body\.caesar-page-index \.app \{([^}]*)\}', CSS)
        desktop = rules[0]
        self.assertIn('grid-template-columns: minmax(0, 1fr) minmax(340px, 390px);', desktop)
        self.assertIn('grid-template-areas: "main order";', desktop)
        self.assertNotIn('!important', desktop)

    def test_tablet_and_mobile_use_fixed_cart_drawer_and_bottom_trigger(self):
        self.assertIn('@media (max-width: 1080px)', CSS)
        self.assertRegex(CSS, r'\.order-panel\s*\{[^}]*position:\s*fixed;')
        self.assertRegex(CSS, r'\.mobile-cart-bar\s*\{[^}]*position:\s*fixed;')
        self.assertIn('body.caesar-page-index.cart-open .order-panel', CSS)
        self.assertIn('body.caesar-page-index.cart-open .cart-scrim', CSS)
        self.assertIn('id="openCartButton"', HTML)
        self.assertIn('aria-controls="orderPanel"', HTML)
        self.assertIn('id="cartScrim"', HTML)
        self.assertIn('id="closeCartButton"', HTML)

    def test_cashier_rail_has_only_required_shortcuts_and_delivery_badge(self):
        rail = re.search(r'<nav class="cashier-rail"[\s\S]*?</nav>', HTML).group(0)
        for required in ('/index.html', '/orders_list.html', '/kitchen.html', '/tables.html',
                         '/delivery.html', '/shift.html', 'id="cashierLockButton"',
                         'id="deliveryOpenCount"'):
            self.assertIn(required, rail)
        self.assertIn('data-role="cashier"', rail)
        self.assertIn('class="rail-count"', rail)
        self.assertIn('body.caesar-page-index [hidden] { display: none !important; }', CSS)

    def test_product_tiles_are_dense_with_minimum_48px_add_target(self):
        self.assertIn('min-height: 88px;', CSS)
        self.assertRegex(CSS, r'\.product-card\s*\{[\s\S]*?min-height:\s*88px;')
        self.assertIn('width: 48px; height: 48px;', CSS)
        self.assertIn('width: 48px; height: 48px; flex: 0 0 48px;', CSS)
        self.assertIn('minmax(165px, 1fr)', CSS)
        self.assertIn('font-size: 9px;', CSS)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr));', CSS)
        self.assertIn('min-width: 46px; min-height: 48px; flex: 1 1 0;', CSS)

    def test_category_row_and_compact_counter_chips_exist(self):
        self.assertIn('id="categoryBar"', HTML)
        self.assertIn('category-tone-', HTML)
        for token in ('counter-strip', 'counter-card', 'counter-icon'):
            self.assertIn(token, CSS)
        for counter in ('counterOrders', 'counterReady', 'counterSales'):
            self.assertIn(f'id="{counter}"', HTML)

    def test_basket_has_one_total_optional_note_and_fixed_checkout(self):
        self.assertEqual(HTML.count('id="total"'), 1)
        self.assertNotIn('id="subtotal"', HTML)
        self.assertIn('mobileCartTotal', HTML)
        self.assertIn("noteToggle.innerHTML=svgIcon('note')", HTML)
        self.assertIn('note.hidden=!note.value', HTML)
        self.assertIn('id="checkoutButton"', HTML)
        self.assertIn('min-height: 58px !important;', CSS)
        self.assertIn('id="printState" aria-live="polite"', HTML)

    def test_delivery_counter_api_and_accessible_drawer_state_are_wired(self):
        self.assertIn("api('/api/delivery/orders')", HTML)
        self.assertIn('refreshDeliveryBadge()', HTML)
        self.assertIn('function syncCartAccessibility()', HTML)
        self.assertIn("window.addEventListener('resize',syncCartAccessibility)", HTML)
        self.assertIn('aria-hidden="true"', HTML)
        self.assertIn('margin: 0;', CSS)
        self.assertIn('top: 12px !important;', CSS)


if __name__ == '__main__':
    unittest.main()
