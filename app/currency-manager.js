/* CAESAR Al-CAESAR · shared offline currency presentation manager */
(() => {
  const endpoint = '/api/settings/currency';
  const storageKey = 'caesar-system-currency';
  const symbols = { SYP: 'ل.س', USD: '$', EUR: '€' };
  const labels = { SYP: 'الليرة السورية', USD: 'الدولار الأمريكي', EUR: 'اليورو' };
  let config = { currency: 'SYP', usd_rate: 0, eur_rate: 0, updated_at: '' };
  let channel = null;

  const safeCurrency = value => Object.hasOwn(symbols, value) ? value : 'SYP';
  const symbol = value => symbols[safeCurrency(value)];
  const escapeRegex = value => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function money(value, options = {}) {
    let amount = Number(value || 0);
    let currency = safeCurrency(options.currency || config.currency);
    if (currency !== 'SYP') {
      const rate = Number(currency === 'USD' ? config.usd_rate : config.eur_rate);
      if (Number.isFinite(rate) && rate > 0) amount /= rate;
      else currency = 'SYP'; // لا تسمِّ مبلغ الليرة دولاراً/يورو إذا لم يتوفر سعر صرف صالح.
    }
    const decimals = currency === 'SYP' ? 0 : 2;
    const number = new Intl.NumberFormat('ar-SY', {
      minimumFractionDigits: options.minimumFractionDigits ?? 0,
      maximumFractionDigits: options.maximumFractionDigits ?? decimals
    }).format(amount);
    return options.withSymbol === false ? number : `${number} ${symbol(currency)}`;
  }

  function replaceLabelText(root, oldSymbol = 'ل.س') {
    if (!root) return;
    const targetSymbol = symbol(config.currency);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const replacements = [];
    let node;
    while ((node = walker.nextNode())) replacements.push(node);
    const oldPattern = escapeRegex(oldSymbol);
    const amountPattern = new RegExp(`([0-9٠-٩٬,.]+)\\s*${oldPattern}(?=\\s|$|[،,:;.)])`, 'g');
    replacements.forEach(text => {
      let value = text.nodeValue;
      if (oldSymbol === 'ل.س') value = value.replace(/الليرة السورية\s*ل\.س/g, labels[config.currency]);
      value = value.replace(amountPattern, `$1 ${targetSymbol}`);
      text.nodeValue = value;
    });
    document.querySelectorAll('[data-currency-symbol]').forEach(el => { el.textContent = targetSymbol; });
    document.querySelectorAll('[data-system-currency-label]').forEach(el => { el.textContent = labels[config.currency]; });
  }

  function updateControls() {
    document.documentElement.dataset.systemCurrency = config.currency;
    document.querySelectorAll('[data-system-currency-control]').forEach(control => {
      if (control.value !== config.currency) control.value = config.currency;
      control.setAttribute('title', `عملة النظام: ${labels[config.currency]}`);
    });
  }

  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify(config)); } catch (_) {}
  }

  function apply(next, options = {}) {
    const previous = symbol(config.currency);
    config = {
      ...config,
      ...next,
      currency: safeCurrency(next.currency || config.currency)
    };
    persist();
    updateControls();
    replaceLabelText(document.body, options.oldSymbol || previous);
    window.dispatchEvent(new CustomEvent('caesar:currency-changed', { detail: { ...config } }));
  }

  async function refresh() {
    const response = await fetch(endpoint, { cache: 'no-store' });
    if (!response.ok) throw new Error('currency unavailable');
    const next = await response.json();
    apply(next);
    return { ...config };
  }

  async function set(nextCurrency, rates = {}) {
    const currency = safeCurrency(nextCurrency);
    const payload = {
      currency,
      usd_rate: rates.usd_rate ?? config.usd_rate ?? 0,
      eur_rate: rates.eur_rate ?? config.eur_rate ?? 0
    };
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || 'تعذر تغيير عملة النظام');
    apply(data, { oldSymbol: symbol(config.currency) });
    if (channel) channel.postMessage({ type: 'currency', data });
    return { ...config };
  }

  function startObserver() {
    const observer = new MutationObserver(records => {
      records.forEach(record => {
        record.addedNodes.forEach(node => {
          if (node.nodeType === Node.TEXT_NODE) replaceLabelText(node.parentElement);
          if (node.nodeType === Node.ELEMENT_NODE) replaceLabelText(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function initialize() {
    try {
      const cached = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (cached && cached.currency) apply(cached);
    } catch (_) {}
    if ('BroadcastChannel' in window) {
      channel = new BroadcastChannel('caesar-currency');
      channel.onmessage = event => {
        if (event.data?.type === 'currency') apply(event.data.data);
      };
    }
    window.addEventListener('storage', event => {
      if (event.key !== storageKey || !event.newValue) return;
      try { apply(JSON.parse(event.newValue)); } catch (_) {}
    });
    startObserver();
    refresh().catch(() => updateControls());
  }

  window.CAESARCurrency = {
    refresh, set, money, symbol: () => symbol(config.currency), label: () => labels[config.currency], get config() { return { ...config }; }
  };
  document.addEventListener('DOMContentLoaded', initialize);
})();
