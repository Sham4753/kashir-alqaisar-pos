(() => {
  'use strict';

  const stateLine = document.getElementById('printState');
  const orderLine = document.getElementById('orderNumber');
  const checkout = document.getElementById('checkoutButton');
  if (!stateLine || !orderLine || !checkout) return;

  const retry = document.createElement('button');
  retry.type = 'button';
  retry.hidden = true;
  retry.textContent = 'إعادة محاولة طباعة الإيصال';
  retry.setAttribute('aria-live', 'polite');
  retry.style.cssText = 'width:100%;min-height:36px;margin-top:5px;border:1px solid #d7a947;border-radius:10px;background:#fffaf0;color:#805b15;font:800 11px Tajawal,Tahoma,sans-serif;cursor:pointer';
  stateLine.insertAdjacentElement('afterend', retry);

  function lastOrderId() {
    const match = String(orderLine.textContent || '').match(/ORD-[A-Z0-9-]+/i);
    return match ? match[0] : '';
  }

  function shouldOfferRetry() {
    const isFailed = stateLine.classList.contains('error');
    retry.hidden = !(isFailed && lastOrderId());
  }

  new MutationObserver(shouldOfferRetry).observe(stateLine, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  new MutationObserver(shouldOfferRetry).observe(orderLine, { childList: true, subtree: true });

  retry.addEventListener('click', async () => {
    const orderId = lastOrderId();
    if (!orderId) return;
    retry.disabled = true;
    retry.textContent = 'جارٍ إعادة الإرسال…';
    stateLine.textContent = 'جارٍ إعادة إرسال الإيصال إلى الطابعة المحلية…';
    stateLine.className = 'print-state';
    try {
      const response = await fetch(`/api/printer/orders/${encodeURIComponent(orderId)}/retry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'receipt' })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || result.print?.message || 'تعذر إعادة إرسال الإيصال');
      stateLine.textContent = 'نجحت إعادة المحاولة: ' + (result.print?.message || 'قبلت الطابعة المهمة الجديدة.');
      stateLine.className = 'print-state success';
      retry.hidden = true;
    } catch (error) {
      stateLine.textContent = error.message || 'تعذرت إعادة محاولة الطباعة.';
      stateLine.className = 'print-state error';
      retry.textContent = 'إعادة محاولة طباعة الإيصال';
    } finally {
      retry.disabled = false;
      shouldOfferRetry();
    }
  });
})();
