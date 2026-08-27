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
  });
})();
