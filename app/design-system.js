/* CAESAR Al-CAESAR · Offline UI behavior */
(() => {
  const page = (location.pathname.split('/').pop() || 'welcome.html').replace(/\.html$/i, '').replace(/[^a-z0-9_-]/gi, '') || 'welcome';
  const body = document.body;
  const key = 'caesar-ui-theme';
  const savedTheme = localStorage.getItem(key);
  const prefersDark = savedTheme !== 'light';

  window.caesarPrepareImage = async function caesarPrepareImage(file, options = {}) {
    const maxDimension = Number(options.maxDimension || 640);
    const maxBytes = Number(options.maxBytes || 180 * 1024);
    if (!file || !String(file.type || '').startsWith('image/')) throw new Error('اختر ملف صورة صالحًا');
    const source = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('تعذر قراءة الصورة'));
      reader.readAsDataURL(file);
    });
    const image = await new Promise((resolve, reject) => {
      const element = new Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(new Error('تعذر فتح الصورة'));
      element.src = source;
    });
    let limit = maxDimension;
    let best = null;
    for (let pass = 0; pass < 5; pass += 1) {
      const scale = Math.min(1, limit / Math.max(image.width, image.height));
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0, width, height);
      for (const quality of [0.84, 0.72, 0.6]) {
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', quality));
        if (!blob) continue;
        if (!best || blob.size < best.blob.size) best = { blob, width, height };
        if (blob.size <= maxBytes) {
          const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(new Error('تعذر تجهيز الصورة'));
            reader.readAsDataURL(blob);
          });
          return { dataUrl, bytes: blob.size, width, height };
        }
      }
      limit = Math.max(160, Math.round(limit * 0.78));
    }
    if (!best || best.blob.size > maxBytes) throw new Error('تعذر ضغط الصورة إلى الحجم المناسب؛ اختر صورة أصغر');
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('تعذر تجهيز الصورة'));
      reader.readAsDataURL(best.blob);
    });
    return { dataUrl, bytes: best.blob.size, width: best.width, height: best.height };
  };

  body.classList.add('caesar-ui', `caesar-page-${page}`, prefersDark ? 'dark' : 'light');

  const updateButton = (button) => {
    const dark = body.classList.contains('dark');
    button.innerHTML = dark
      ? '<svg class="q-line-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path></svg>'
      : '<svg class="q-line-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2Z"></path></svg>';
    button.title = dark ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن';
    button.setAttribute('aria-label', button.title);
  };

  const themeButton = document.createElement('button');
  themeButton.type = 'button';
  themeButton.className = 'q-theme-toggle';
  updateButton(themeButton);
  themeButton.addEventListener('click', () => {
    const dark = body.classList.toggle('dark');
    body.classList.toggle('light', !dark);
    localStorage.setItem(key, dark ? 'dark' : 'light');
    updateButton(themeButton);
  });

  const syncChannel = 'BroadcastChannel' in window ? new BroadcastChannel('caesar-menu-sync') : null;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const request = args[0] instanceof Request ? args[0] : new Request(String(args[0] || ''), args[1]);
    const path = new URL(request.url, window.location.href).pathname;
    const changesData = ['/api/category', '/api/product', '/api/settings/restaurant', '/api/settings/currency'];
    if (response.ok && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) && changesData.some((prefix) => path.startsWith(prefix))) {
      syncChannel?.postMessage({ type: 'menu-or-settings-changed', at: Date.now() });
    }
    return response;
  };

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.querySelector('.q-theme-toggle')) document.body.appendChild(themeButton);
    applyLineIcons();
    cleanNativeOptionIcons();
    cleanResidualInterfacePictographs();
    watchDynamicIcons();
    loadRestaurantIdentity();
    enforceNavigationPrivileges();
  });

  const iconMap = {
    sale: '<path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h4"/>',
    receipt: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3zM9 8h6M9 12h6M9 16h4"/>',
    printer: '<path d="M6 9V3h12v6M6 18H4V10h16v8h-2M7 14h10v7H7zM17 11h.01"/>',
    cash: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M8 14h.01M12 14h5"/>',
    kitchen: '<path d="M5 3v7M8 3v7M5 7h3M8 3v18M15 3v8a3 3 0 0 0 6 0V3M18 14v7"/>',
    table: '<path d="M4 10h16v5H4zM7 15v6M17 15v6M8 10V6h8v4"/>',
    box: '<path d="m3 7 9-4 9 4-9 4-9-4Z"/><path d="M3 7v10l9 4 9-4V7M12 11v10"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    users: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6M19 21v-2a6 6 0 0 0-3-5.2"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.18 2.18-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.04 1.56V21h-3.08v-.08a1.7 1.7 0 0 0-1.04-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-2.18-2.18.06-.06A1.7 1.7 0 0 0 6.8 15a1.7 1.7 0 0 0-1.56-1.04H5v-3.08h.24A1.7 1.7 0 0 0 6.8 9.84 1.7 1.7 0 0 0 6.46 7.96l-.06-.06 2.18-2.18.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.04-1.56V4.5h3.08v.06a1.7 1.7 0 0 0 1.04 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.18 2.18-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.04H21v3.08h-.04A1.7 1.7 0 0 0 19.4 15Z"/>',
    shield: '<path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6l8-3Z"/><path d="m9 12 2 2 4-4"/>',
    eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.9-3.9L3 10M4 5v5h5M4 13a8 8 0 0 0 14.9 3.9L21 14M20 19v-5h-5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    delete: '<path d="M4 7h16M10 11v6M14 11v6M9 7V4h6v3M6 7l1 14h10l1-14"/>',
    back: '<path d="m14 6-6 6 6 6M9 12h11"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  };

  function iconType(text) {
    const label = String(text || '').replace(/\s+/g, ' ').trim();
    if (/حذف|مسح|إعادة ضبط|خروج/.test(label)) return 'delete';
    if (/رجوع|تراجع|إلغاء/.test(label)) return 'back';
    if (/طابعة|طباعة|إيصال/.test(label)) return 'printer';
    if (/درج|نقد|دفع|بطاقة/.test(label)) return 'cash';
    if (/مطبخ/.test(label)) return 'kitchen';
    if (/طاولة|صالة/.test(label)) return 'table';
    if (/سفري|ديليفري|طلب|بيع|فاتورة/.test(label)) return 'receipt';
    if (/قسم|أقسام|مفضلة/.test(label)) return 'box';
    if (/مخزون|مواد خام|منيو|صنف|منتج/.test(label)) return 'box';
    if (/تقارير|مالية|مصروف|دين|جرد/.test(label)) return 'chart';
    if (/موافقة|اعتماد|حساسة|حماية/.test(label)) return 'shield';
    if (/سجل|تدقيق/.test(label)) return 'receipt';
    if (/موظف|مستخدم|وردية|دوام|دعم/.test(label)) return 'users';
    if (/معلومات المطعم|إعداد|نسخ احتياطي|USB|ربط|QR|دليل الإغلاق|تحديث النظام/.test(label)) return 'settings';
    if (/قفل/.test(label)) return 'lock';
    if (/بحث|باركود/.test(label)) return 'search';
    if (/حفظ|تأكيد|إضافة|إنشاء|تصدير|استيراد|تحميل/.test(label)) return 'download';
    return '';
  }

  function buildIcon(type) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', 'q-line-icon');
    svg.innerHTML = iconMap[type] || iconMap.sale;
    return svg;
  }

  function pictographIconType(text) {
    const value = String(text || '').toLowerCase();
    if (/طباعة|printer|receipt/.test(value)) return 'printer';
    if (/عرض|عين|eye|preview/.test(value)) return 'eye';
    if (/تحديث|إعادة|refresh|retry/.test(value)) return 'refresh';
    if (/إضافة|plus|add/.test(value)) return 'plus';
    if (/تنزيل|تحميل|download|excel|pdf/.test(value)) return 'download';
    if (/إعداد|ضبط|settings|printer settings/.test(value)) return 'settings';
    if (/قفل|lock|password/.test(value)) return 'lock';
    if (/نقد|بطاقة|cash|card|payment/.test(value)) return 'cash';
    return '';
  }

  function applyLineIcons() {
    document.querySelectorAll('.menu-group summary').forEach((summary) => {
      if (summary.dataset.qLineIconApplied === 'true') return;
      const type = iconType(summary.textContent);
      if (!type) return;
      summary.insertBefore(buildIcon(type), summary.firstChild);
      summary.dataset.qLineIconApplied = 'true';
    });
    document.querySelectorAll('button, a, h1, h2, h3').forEach((element) => {
      if (element.dataset.qLineIconApplied === 'true' || element.querySelector('svg')) return;
      const firstText = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && /^\s*[\p{Extended_Pictographic}]/u.test(node.textContent || ''));
      const type = iconType(element.textContent) || pictographIconType(firstText?.textContent);
      if (!type) return;
      if (!firstText && !/^(H1|H2|H3)$/.test(element.tagName)) return;
      if (firstText) firstText.textContent = (firstText.textContent || '').replace(/^\s*[\p{Extended_Pictographic}\uFE0F\u200D\s]+/u, '');
      element.insertBefore(buildIcon(type), element.firstChild);
      element.dataset.qLineIconApplied = 'true';
    });
  }

  function cleanNativeOptionIcons(root = document) {
    root.querySelectorAll?.('option').forEach((option) => {
      if (option.dataset.qPictographCleaned === 'true') return;
      option.textContent = String(option.textContent || '')
        .replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
      option.dataset.qPictographCleaned = 'true';
    });
  }

  function cleanResidualInterfacePictographs(root = document) {
    root.querySelectorAll?.('button, a, h1, h2, h3, .toast, #toast').forEach((element) => {
      if (element.querySelector('svg') || element.querySelector('img')) return;
      const value = String(element.textContent || '');
      if (!/[\p{Extended_Pictographic}]/u.test(value)) return;
      element.childNodes.forEach((node) => {
        if (node.nodeType !== Node.TEXT_NODE) return;
        node.textContent = String(node.textContent || '').replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, '').replace(/\s{2,}/g, ' ');
      });
    });
  }

  function watchDynamicIcons() {
    const observer = new MutationObserver((changes) => {
      changes.forEach((change) => {
        change.addedNodes.forEach((node) => {
          if (node.nodeType !== Node.ELEMENT_NODE) return;
          cleanNativeOptionIcons(node);
          cleanResidualInterfacePictographs(node);
          if (node.matches?.('option')) cleanNativeOptionIcons(node.parentElement || document);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

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
        document.title = document.title.replace('كاشير قيصر قيصر', name);
      }
      if (!logo.startsWith('data:image/')) return;
      document.querySelectorAll('.q-appbar-brand-mark, .brand-mark, .mark, [data-restaurant-logo]').forEach((mark) => {
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

  async function enforceNavigationPrivileges() {
    const managerOnlyPages = new Set([
      'settings.html', 'printer_settings.html', 'menu_manager.html', 'employees.html',
      'raw_materials.html', 'analytics.html', 'manager_ops.html', 'expenses.html'
    ]);
    try {
      const response = await fetch('/api/auth/me', { cache: 'no-store' });
      if (!response.ok) return;
      const currentUser = await response.json();
      if (currentUser.role === 'manager') return;
      document.querySelectorAll('a[href]').forEach((link) => {
        const pageName = (link.getAttribute('href') || '').split('?')[0].split('/').pop();
        if (!managerOnlyPages.has(pageName)) return;
        link.hidden = true;
        link.setAttribute('aria-hidden', 'true');
        link.setAttribute('tabindex', '-1');
      });
    } catch (_) {
      // يبقى الخادم هو الحاجز النهائي عندما يتعذر التحقق من الدور في الواجهة.
    }
  }
})();

// قائمة يمنى بديلة (نسخ/قص/لصق/تحديد الكل): مع إطفاء DevTools (debug=False في
// caesar_desktop.py) تختفي قائمة الفأرة اليمنى الأصلية من WebView2، فهما
// مرتبطتان معاً في هذا الإصدار من pywebview. هذه القائمة الخفيفة تعوّض ذلك
// بالكامل بجافاسكريبت عادي، وتعمل على أي حقل/نص بكل شاشات التطبيق دون الحاجة
// لأي إذن نظام إضافي. اختصارات الكيبورد (Ctrl+C/V/A/X) تبقى تعمل بشكل طبيعي
// دائماً وبشكل مستقل تماماً عن هذه القائمة.
(function () {
  var menu = null;
  function closeMenu() { if (menu) { menu.remove(); menu = null; } }
  function addItem(label, handler) {
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'ctx-menu-item'; btn.textContent = label;
    btn.addEventListener('mousedown', function (e) { e.preventDefault(); e.stopPropagation(); handler(); closeMenu(); });
    menu.appendChild(btn);
    return btn;
  }
  document.addEventListener('click', closeMenu);
  document.addEventListener('scroll', closeMenu, true);
  document.addEventListener('contextmenu', function (e) {
    e.preventDefault();
    closeMenu();
    var el = e.target;
    var isField = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && !el.disabled;
    var isEditableText = isField || el.isContentEditable;
    menu = document.createElement('div');
    menu.className = 'ctx-menu';
    if (isEditableText) {
      addItem('قص  /  Cut', function () { try { document.execCommand('cut'); } catch (_) { } });
      addItem('نسخ  /  Copy', function () { try { document.execCommand('copy'); } catch (_) { } });
      addItem('لصق  /  Paste', function () {
        el.focus();
        if (navigator.clipboard && navigator.clipboard.readText) {
          navigator.clipboard.readText().then(function (text) {
            if (!text) return;
            if (typeof el.setRangeText === 'function' && el.selectionStart != null) {
              el.setRangeText(text, el.selectionStart, el.selectionEnd, 'end');
            } else { el.value = text; }
            el.dispatchEvent(new Event('input', { bubbles: true }));
          }).catch(function () { try { document.execCommand('paste'); } catch (_) { } });
        } else { try { document.execCommand('paste'); } catch (_) { } }
      });
      addItem('تحديد الكل  /  Select All', function () {
        el.focus();
        if (typeof el.select === 'function') { el.select(); }
        else { try { document.execCommand('selectAll'); } catch (_) { } }
      });
    } else {
      addItem('نسخ  /  Copy', function () { try { document.execCommand('copy'); } catch (_) { } });
      addItem('تحديد الكل  /  Select All', function () {
        var range = document.createRange();
        range.selectNodeContents(document.body);
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      });
    }
    document.body.appendChild(menu);
    var maxX = window.innerWidth - menu.offsetWidth - 8, maxY = window.innerHeight - menu.offsetHeight - 8;
    menu.style.left = Math.max(4, Math.min(e.clientX, maxX)) + 'px';
    menu.style.top = Math.max(4, Math.min(e.clientY, maxY)) + 'px';
  }, true);
})();

