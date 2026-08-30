from pathlib import Path
import re

html = Path('/home/ubuntu/kashir-alqaisar-pos/app/index.html').read_text(encoding='utf-8')
scripts = re.findall(r'<script(?![^>]*src)[^>]*>(.*?)</script>', html, flags=re.S | re.I)
Path('/tmp/kashir_inline.js').write_text('\n\n'.join(scripts), encoding='utf-8')
print(f'extracted {len(scripts)} inline script blocks')
print(f'javascript bytes: {Path("/tmp/kashir_inline.js").stat().st_size}')
if not scripts:
    raise SystemExit('no inline scripts found')
if html.count('id="mainLayout"') != 1:
    raise SystemExit('mainLayout must appear exactly once')
if html.count('id="productsGrid"') != 1 or html.count('id="cartItems"') != 1:
    raise SystemExit('required POS containers are duplicated or missing')
print('required POS containers: ok')
print('desktop grid order: cart catalog')
