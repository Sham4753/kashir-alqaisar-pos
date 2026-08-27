/* Kashir Al-Qaisar · Offline UI behavior */
(() => {
  const page = (location.pathname.split('/').pop() || 'welcome.html').replace(/\.html$/i, '').replace(/[^a-z0-9_-]/gi, '') || 'welcome';
  const body = document.body;
  const key = 'qaisar-ui-theme';
  const savedTheme = localStorage.getItem(key);

  body.classList.add('qaisar-ui', `qaisar-page-${page}`);
  if (savedTheme === 'dark') body.classList.add('dark');

  const updateButton = (button) => {
    const dark = body.classList.contains('dark');
    button.textContent = dark ? '☀' : '◐';
    button.title = dark ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن';
    button.setAttribute('aria-label', button.title);
  };

  const themeButton = document.createElement('button');
  themeButton.type = 'button';
  themeButton.className = 'q-theme-toggle';
  updateButton(themeButton);
  themeButton.addEventListener('click', () => {
    body.classList.toggle('dark');
    localStorage.setItem(key, body.classList.contains('dark') ? 'dark' : 'light');
    updateButton(themeButton);
  });

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.querySelector('.q-theme-toggle')) document.body.appendChild(themeButton);
    loadRestaurantIdentity();
  });

  async function loadRestaurantIdentity() {
    try {
      const response = await fetch('/api/restaurant/identity', { cache: 'no-store' });
      if (!response.ok) return;
      const identity = await response.json();
      const name = String(identity.name || '').trim();
      const logo = String(identity.brand_logo_data || '');
      if (name) {
        document.querySelectorAll('.q-appbar-brand').forEach((brand) => {
          const label = brand.querySelector('.q-brand-name') || brand.lastElementChild;
          if (label && label !== brand.querySelector('.q-appbar-brand-mark')) label.textContent = name;
        });
        document.querySelectorAll('[data-restaurant-name]').forEach((node) => { node.textContent = name; });
        document.title = document.title.replace('كاشير القيصر', name);
      }
      if (!logo.startsWith('data:image/')) return;
      document.querySelectorAll('.q-appbar-brand-mark, .brand-mark, [data-restaurant-logo]').forEach((mark) => {
        if (mark.dataset.restaurantLogoApplied === 'true') return;
        mark.textContent = '';
        const image = document.createElement('img');
        image.src = logo; image.alt = name ? `شعار ${name}` : 'شعار المطعم';
        mark.appendChild(image);
        mark.classList.add('has-restaurant-logo');
        mark.dataset.restaurantLogoApplied = 'true';
      });
    } catch (_) {
      // تبقى علامة النظام الافتراضية ظاهرة عند تعذر تحميل الهوية، كي لا تتعطل أي شاشة.
    }
  }
})();
