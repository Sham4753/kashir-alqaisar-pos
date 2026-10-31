import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / 'app' / 'pos-modern.css').read_text(encoding='utf-8')


class PosDesktopGridTests(unittest.TestCase):
    def test_desktop_grid_matches_hidden_sidebar_drawer(self):
        """السايدبار درج مخفي (position: fixed)، فشبكة سطح المكتب يجب أن تكون عمودين فقط."""
        self.assertIn('position: fixed !important;', CSS)  # sidebar drawer rule exists
        rules = re.findall(r'body\.caesar-page-index \.app \{([^}]*)\}', CSS)
        important = [r for r in rules if 'grid-template-columns' in r and '!important' in r]
        # آخر قاعدة !important على سطح المكتب هي التي تُطبَّق فعلياً.
        last = important[-1]
        columns = re.search(r'grid-template-columns:\s*([^;]+?)\s*!important', last).group(1)
        tracks = re.findall(r'minmax\([^)]*\)|\d+px|\dfr', columns)
        self.assertEqual(len(tracks), 2, columns)

    def test_cart_panel_is_wider_and_item_notes_have_a_visible_field(self):
        self.assertIn('minmax(560px, 600px)', CSS)
        self.assertIn('.cart-item-note', CSS)
        self.assertIn('font-size: 9px;', CSS)
        self.assertIn('min-height: 220px;', CSS)


if __name__ == '__main__':
    unittest.main()
