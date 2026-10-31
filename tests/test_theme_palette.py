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

    def test_one_restaurant_palette_and_semantic_button_hierarchy_are_defined(self):
        self.assertEqual(self.light['--q-brand'], '#c2410c')
        self.assertEqual(self.light['--q-bg'], '#f7f7f7')
        self.assertEqual(self.dark['--q-bg'], '#111111')
        self.assertEqual(self.light['--q-ink'], '#111111')
        self.assertEqual(self.dark['--q-ink'], '#ffffff')
        self.assertEqual(self.light['--q-on-brand'], '#ffffff')
        self.assertEqual(self.dark['--q-on-brand'], '#111111')
        for filename in ('design-system.css', 'theme.css'):
            source = (APP / filename).read_text(encoding='utf-8')
            self.assertNotRegex(source, r'--q-(?:bg|surface|ink|brand|success|warning|danger)\s*:')
        self.assertIn('--color-bg: var(--q-bg);', self.theme)
        self.assertIn('--color-text-on-primary: var(--q-on-brand);', self.theme)
        self.assertIn('background: var(--q-surface-muted) !important;', self.theme)
        self.assertIn('background: var(--q-brand) !important;', self.theme)
        self.assertIn('background: var(--q-danger) !important;', self.theme)
        self.assertIn('background: var(--q-warning) !important;', self.theme)
        self.assertIn('body.caesar-page-index .nav a:is(.active, :hover)', self.theme)

    def test_pos_basket_is_narrower_and_product_icon_spaces_are_larger(self):
        pos = (APP / 'pos-modern.css').read_text(encoding='utf-8')
        self.assertIn('minmax(350px, 390px)', pos)
        self.assertIn('min-height: 86px;', pos)
        self.assertIn('height: 116px;', pos)
        self.assertIn('width: 48px; height: 48px;', pos)
        self.assertIn('width: 28px; height: 28px;', pos)
        self.assertIn('color: var(--q-ink) !important;', self.theme)
        self.assertIn('color: var(--q-on-brand) !important;', self.theme)

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

    def test_every_page_uses_cache_busted_shared_palette_and_theme(self):
        pages = list(APP.glob('*.html'))
        self.assertGreaterEqual(len(pages), 20)
        for page in pages:
            html = page.read_text(encoding='utf-8')
            for asset in ('design-system.css', 'palette-v3.css', 'theme.css'):
                self.assertRegex(
                    html,
                    rf'href=["\'][^"\']*{re.escape(asset)}\?v=20261031-orange-v2["\']',
                    f'{page.name} لا يحمل {asset} بإصدار حديث',
                )


if __name__ == '__main__':
    unittest.main()
