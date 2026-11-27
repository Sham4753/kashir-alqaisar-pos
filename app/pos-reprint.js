(() => {
  'use strict';

  const openButton = document.getElementById('cashierReprintButton');
  const overlay = document.getElementById('reprintOverlay');
  const closeButton = document.getElementById('reprintCloseButton');
  const search = document.getElementById('reprintSearch');
  const list = document.getElementById('reprintOrdersList');
  const status = document.getElementById('reprintStatus');
  if (!openButton || !overlay || !closeButton || !search || !list || !status) return;

  let orders = [];
  const text = (value) => String(value == null ? '' : value);
  const showStatus = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle('error', error);
  };
  function orderAmount(order) {
    const currency = text(order.currency || 'SYP');
    const rate = Number(order.exchange_rate || 0);
    const amount = Number(order.total || 0);
    const display = ['USD', 'EUR'].includes(currency) && rate > 0 ? amount / rate : amount;
    const symbol = { SYP: 'ل.س', SAR: 'ر.س', USD: '$', EUR: '€' }[currency] || currency;
    return Number.isFinite(display) ? display.toLocaleString('ar-SY', { maximumFractionDigits: 2 }) + ' ' + symbol : '';
  }

  function renderOrders() {
    const query = search.value.trim().toLocaleLowerCase('ar');
    const matches = orders.filter((order) => {
      const searchable = [order.display_no, order.id, order.customer]
        .map(text).join(' ').toLocaleLowerCase('ar');
      return !query || searchable.includes(query);
    });
    list.replaceChildren();
    if (!matches.length) {
      const empty = document.createElement('div');
      empty.className = 'held-empty';
      empty.textContent = orders.length ? 'لا توجد فاتورة مطابقة.' : 'لا توجد فواتير اليوم.';
      list.append(empty);
      return;
    }
    matches.forEach((order) => {
      const row = document.createElement('article');
      row.className = 'reprint-order';
      const details = document.createElement('div');
      details.className = 'reprint-order-details';
      const number = document.createElement('strong');
      number.textContent = text(order.display_no || order.id);
      const info = document.createElement('small');
      info.textContent = [order.customer, order.timestamp, orderAmount(order)].map(text).filter(Boolean).join(' · ');
      details.append(number, info);
      const actions = document.createElement('div');
      actions.className = 'reprint-order-actions';
      [['receipt', 'إيصال'], ['kitchen', 'مطبخ']].forEach(([type, label]) => {
        const action = document.createElement('button');
        action.type = 'button';
        action.className = 'reprint-action';
        action.dataset.orderId = text(order.id);
        action.dataset.type = type;
        action.textContent = 'إعادة ' + label;
        actions.append(action);
      });
      row.append(details, actions);
      list.append(row);
    });
  }

  async function loadOrders() {
    list.replaceChildren();
    const loading = document.createElement('div');
    loading.className = 'held-empty';
    loading.textContent = 'جارٍ تحميل فواتير اليوم…';
    list.append(loading);
    showStatus('');
    try {
      const response = await fetch('/api/orders?scope=today&limit=50', { cache: 'no-store' });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'تعذر تحميل الفواتير');
      orders = Array.isArray(result) ? result : (result.orders || []);
      renderOrders();
    } catch (error) {
      orders = [];
      list.replaceChildren();
      const message = document.createElement('div');
      message.className = 'held-empty';
      message.textContent = error.message || 'تعذر تحميل فواتير اليوم.';
      list.append(message);
      showStatus(error.message || 'تعذر تحميل الفواتير.', true);
    }
  }

  function open() {
    overlay.hidden = false;
    overlay.classList.add('show');
    search.value = '';
    loadOrders();
    search.focus();
  }

  function close() {
    overlay.classList.remove('show');
    overlay.hidden = true;
    openButton.focus();
  }

  openButton.addEventListener('click', open);
  closeButton.addEventListener('click', close);
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) close();
  });
  search.addEventListener('input', renderOrders);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !overlay.hidden) close();
  });
  list.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-order-id][data-type]');
    if (!button || button.disabled) return;
    const order = orders.find((item) => text(item.id) === button.dataset.orderId);
    const orderNo = text(order && (order.display_no || order.id));
    const kind = button.dataset.type;
    button.disabled = true;
    const original = button.textContent;
    button.textContent = 'جارٍ الإرسال…';
    showStatus('جارٍ إرسال نسخة ' + (kind === 'kitchen' ? 'المطبخ' : 'الإيصال') + ' للفاتورة ' + orderNo + '…');
    try {
      const response = await fetch('/api/printer/orders/' + encodeURIComponent(button.dataset.orderId) + '/print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: kind }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || result.print?.message || 'تعذرت إعادة الطباعة');
      showStatus('أُرسلت نسخة ' + (kind === 'kitchen' ? 'المطبخ' : 'الإيصال') + ' للفاتورة ' + orderNo + ' إلى الطابعة.');
      button.textContent = 'تم الإرسال';
    } catch (error) {
      showStatus(error.message || 'تعذرت إعادة الطباعة.', true);
      button.textContent = original;
    } finally {
      button.disabled = false;
    }
  });
})();
