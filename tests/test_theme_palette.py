import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'


def luminance(hex_color):
    values = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def contrast(first, second):
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def tokens(block):
    return dict(re.findall(r'(--q-[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;', block))


class ThemePaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palette = (APP / 'palette-v3.css').read_text(encoding='utf-8')
        cls.theme = (APP / 'theme.css').read_text(encoding='utf-8')
        cls.pos = (APP / 'pos-modern.css').read_text(encoding='utf-8')
        cls.index = (APP / 'index.html').read_text(encoding='utf-8')
        match = re.search(
            r':root,\s*body\.caesar-ui\.light,\s*body\.caesar-ui:not\(\.dark\)\s*\{(.*?)\}\s*body\.caesar-ui\.dark\s*\{(.*?)\}',
            cls.palette,
            re.S,
        )
        if not match:
            raise AssertionError('لوحة ألوان light/dark المركزية غير موجودة')
        cls.light = tokens(match.group(1))
        cls.dark = tokens(match.group(2))

    def test_brand_and_status_button_text_meets_wcag_contrast(self):
        for palette_name, palette in (('فاتح', self.light), ('داكن', self.dark)):
            for action in ('brand', 'success', 'warning', 'danger'):
                foreground = palette[f'--q-on-{action}']
                background = palette[f'--q-{action}']
                ratio = contrast(foreground, background)
                self.assertGreaterEqual(
                    ratio, 4.5,
                    f'تباين زر {action} في الوضع {palette_name} منخفض: {ratio:.2f}:1',
                )

    def test_shared_light_and_dark_palette_remains_the_single_color_source(self):
        self.assertEqual(self.light['--q-brand'], '#c2410c')
        self.assertEqual(self.light['--q-bg'], '#f7f7f7')
        self.assertEqual(self.dark['--q-bg'], '#111111')
        self.assertEqual(self.light['--q-ink'], '#111111')
        self.assertEqual(self.dark['--q-ink'], '#ffffff')
        self.assertEqual(self.light['--q-on-brand'], '#ffffff')
        self.assertEqual(self.dark['--q-on-brand'], '#111111')
        for filename in ('design-system.css', 'theme.css', 'pos-modern.css'):
            source = (APP / filename).read_text(encoding='utf-8')
            self.assertNotRegex(source, r'--q-(?:bg|surface|ink|brand|success|warning|danger)\s*:')
        self.assertIn('--color-bg: var(--q-bg);', self.theme)
        self.assertIn('--color-text-on-primary: var(--q-on-brand);', self.theme)
        self.assertIn('background: var(--q-surface-muted) !important;', self.theme)
        self.assertIn('background: var(--q-brand) !important;', self.theme)
        self.assertIn('background: var(--q-danger) !important;', self.theme)
        self.assertIn('background: var(--q-warning) !important;', self.theme)
        self.assertIn('body.caesar-page-index .nav a:is(.active, :hover)', self.theme)

    def test_pos_loads_design_system_palette_and_layout_without_legacy_theme_layer(self):
        for stylesheet in ('design-system.css', 'palette-v3.css', 'pos-modern.css'):
            self.assertRegex(self.index, rf'href="/{re.escape(stylesheet)}\?v=20261125-pos-v1"')
        self.assertNotRegex(self.index, r'href="[^"]*theme\.css')
        self.assertNotRegex(self.pos, r'#[0-9a-fA-F]{3,8}\b')
        self.assertIn('var(--q-brand)', self.pos)
        self.assertIn('var(--q-surface)', self.pos)
        self.assertIn('var(--q-line)', self.pos)

    def test_pos_cart_is_compact_single_total_and_adapts_to_a_bottom_sheet(self):
        self.assertIn('minmax(340px, 390px)', self.pos)
        self.assertIn('position: fixed;', self.pos)
        self.assertIn('body.caesar-page-index.cart-open .order-panel', self.pos)
        self.assertIn('body.caesar-page-index .mobile-cart-bar', self.pos)
        self.assertIn('min-height: 58px !important;', self.pos)
        self.assertIn('width: 48px; height: 48px;', self.pos)
        self.assertEqual(self.index.count('id="total"'), 1)
        self.assertIn("noteToggle.innerHTML=svgIcon('note')", self.index)

    def test_cashier_navigation_delivery_badge_and_role_visibility_are_wired(self):
        self.assertIn('class="cashier-rail"', self.index)
        self.assertIn('data-role="cashier"', self.index)
        self.assertIn('id="deliveryOpenCount"', self.index)
        self.assertIn("api('/api/delivery/orders')", self.index)
        self.assertIn("node.hidden=!allowed", self.index)
        self.assertIn("document.getElementById('cashierLockButton').addEventListener('click',lockScreen)", self.index)
        self.assertIn("api('/api/auth/lock'", self.index)
        self.assertIn("api('/api/auth/unlock'", self.index)

    def test_delivery_label_is_localized_without_changing_internal_order_value(self):
        self.assertIn('>توصيل</button>', self.index)
        self.assertIn('data-type="ديليفري"', self.index)
        self.assertIn("order.type==='ديليفري'?'توصيل'", self.index)
        self.assertNotIn('>دليفري<', self.index)
        self.assertNotIn('>التوصيل<', self.index)

    def test_entry_and_setup_screens_join_the_shared_light_workspace(self):
        for selector in (
            'html body.caesar-page-welcome {',
            'html body.caesar-page-welcome .profile-card',
            'html body.caesar-page-setup {',
        ):
            self.assertIn(selector, self.theme)
        welcome = (APP / 'welcome.html').read_text(encoding='utf-8')
        self.assertIn('class="min-h-screen flex flex-col text-white"', welcome)
        self.assertIn('20261031-orange-v2', welcome)

    def test_all_pages_keep_cache_busted_shared_assets_with_pos_specific_exception(self):
        pages = list(APP.glob('*.html'))
        self.assertGreaterEqual(len(pages), 20)
        for page in pages:
            html = page.read_text(encoding='utf-8')
            if page.name == 'index.html':
                for asset in ('design-system.css', 'palette-v3.css', 'pos-modern.css'):
                    self.assertRegex(html, rf'href="[^"]*{re.escape(asset)}\?v=20261125-pos-v1"')
                self.assertNotRegex(html, r'href="[^"]*theme\.css')
                continue
            for asset in ('design-system.css', 'palette-v3.css', 'theme.css'):
                self.assertRegex(
                    html,
                    rf'href=["\'][^"\']*{re.escape(asset)}\?v=20261031-orange-v2["\']',
                    f'{page.name} لا يحمل {asset} بإصدار حديث',
                )


if __name__ == '__main__':
    unittest.main()
