from pathlib import Path
import unicodedata
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

root = Path(__file__).resolve().parents[1]
for filename in ('Tajawal-Regular.ttf', 'Tajawal-Bold.ttf'):
    path = root / 'app' / 'fonts' / filename
    font = TTFont(str(path))
    best = font.getBestCmap()
    additions = {}
    for cp in range(0xFE80, 0xFEFF):
        if cp in best:
            continue
        normalized = unicodedata.normalize('NFKC', chr(cp))
        if len(normalized) == 1:
            base_cp = ord(normalized)
            glyph = best.get(base_cp)
            if glyph:
                additions[cp] = glyph
    for table in font['cmap'].tables:
        if table.isUnicode():
            table.cmap.update(additions)
    font.save(str(path))
    after = TTFont(str(path)).getBestCmap()
    missing = [cp for cp in range(0xFE80, 0xFEFF) if cp not in after]
    print(filename, 'added', len(additions), 'presentation aliases; remaining missing:', len(missing))
