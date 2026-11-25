import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';

const indexPath = resolve(process.cwd(), 'app', 'index.html');
const html = readFileSync(indexPath, 'utf8');
const posCssPath = resolve(process.cwd(), 'app', 'pos-modern.css');
const posCss = readFileSync(posCssPath, 'utf8');
const retryPath = resolve(process.cwd(), 'app', 'pos-retry.js');
const retryScript = readFileSync(retryPath, 'utf8');
const currencyPath = resolve(process.cwd(), 'app', 'currency-manager.js');
const currencyScript = readFileSync(currencyPath, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/gi)];

function requireText(value, text, message) {
  if (!value.includes(text)) throw new Error(message || `النص أو المسار المطلوب غير موجود: ${text}`);
}

if (!scripts.length) throw new Error('لم يتم العثور على JavaScript لواجهة نقطة البيع');
if (html.includes('window.print') || html.includes('window.open')) {
  throw new Error('لا يجب أن تستدعي واجهة الإيصال نافذة أو مربع طباعة المتصفح');
}

// Cache-busted visual layers: POS reads colors only from the shared palette.
for (const stylesheet of ['design-system.css', 'palette-v3.css', 'pos-modern.css']) {
  requireText(html, `/${stylesheet}?v=20261125-pos-v1`, `ملف التنسيق ${stylesheet} أو إصداره غير موجود`);
}
if (/href=["'][^"']*theme\.css/.test(html)) {
  throw new Error('طبقة theme.css القديمة ما زالت محمّلة فوق شاشة POS');
}
if (/--q-(?:bg|surface|ink|brand|success|warning|danger)\s*:/.test(posCss)) {
  throw new Error('يجب أن تأتي tokens اللونية من palette-v3.css فقط');
}

// Responsive cashier workspace, drawer, single total, note, and unified icons.
for (const required of [
  'class="cashier-rail"',
  'data-role="cashier"',
  'id="deliveryOpenCount"',
  'id="categoryBar"',
  'id="mobileCartBar"',
  'id="openCartButton"',
  'aria-controls="orderPanel"',
  'id="cartScrim"',
  'id="closeCartButton"',
  'id="mobileCartTotal"',
  'id="mobileCartCount"',
  'id="paymentOverlay"',
  'id="paymentAdjustment"',
  'id="paymentTotal"',
  'id="cashReceived"',
  'id="changeDue"',
  'id="managerApprovalFields"',
  'id="confirmPaymentButton"',
  'id="printState" aria-live="polite"',
  "noteToggle.innerHTML=svgIcon('note')",
  'function syncCartAccessibility()',
  'function svgIcon(name)',
  'aria-hidden="true"'
]) requireText(html, required);
for (const label of ['بيع', 'طلبات', 'مطبخ', 'طاولات', 'توصيل', 'وردية', 'قفل']) {
  requireText(html, label, `اختصار الكاشير ${label} غير موجود`);
}
if (html.split('id="total"').length - 1 !== 1 || html.includes('id="subtotal"')) {
  throw new Error('يجب عرض إجمالي واحد فقط في السلة');
}
if (!posCss.includes('@media (max-width: 1080px)') ||
    !posCss.includes('body.caesar-page-index.cart-open .order-panel') ||
    !posCss.includes('body.caesar-page-index .mobile-cart-bar')) {
  throw new Error('الدرج السفلي أو الشريط الثابت للجوال والتابلت غير مكتمل');
}
if (!posCss.includes('width: 48px; height: 48px;') || !posCss.includes('min-height: 88px;')) {
  throw new Error('أهداف اللمس لبلاطات الأصناف يجب أن تكون 48px على الأقل');
}
if (/>(?:دليفري|ديليفري|التوصيل)</.test(html)) {
  throw new Error('تسمية التوصيل الظاهرة غير موحدة');
}

// Preserve order creation, currency formatting, roles, lock, and printer outcomes.
for (const route of [
  '/api/auth/me',
  '/api/auth/lock',
  '/api/auth/unlock',
  '/api/menu',
  '/api/restaurant/identity',
  '/api/settings/features',
  '/api/dashboard/counters',
  '/api/dashboard/daily',
  '/api/delivery/orders',
  '/api/orders',
  '/api/held-orders'
]) requireText(html, route, `مسار API أساسي مفقود: ${route}`);
for (const source of [
  "payment:'نقدي'",
  "kitchen_release:'now'",
  'rounding_adjustment:adjustment',
  'cash_received:cashReceived',
  'function updatePaymentPreview(clearError=true)',
  'function openPayment()',
  'money(total,true)',
  'updatePaymentPreview(false)',
  "paymentEl.approval.hidden=!needsManager",
  "event.stopImmediatePropagation()",
  'paymentEl.overlay.addEventListener(\'keydown\'',
  'event.stopImmediatePropagation(); closePayment();',
  'payload.manager_approval={username:',
  'product_id:item.id',
  'note:item.note||',
  "api('/api/auth/lock'",
  "api('/api/auth/unlock'",
  "node.hidden=!allowed",
  "state.currency=identity.currency",
  "currency:'SYP'",
  "printed.status",
  "displayPrintState('تمت الطباعة الصامتة: '+message",
  "تعذر التحقق من حالة الطباعة",
  "راجع حالة الطابعة"
]) requireText(html, source, `سلوك تجاري أو عملة أو طباعة مفقود: ${source}`);
for (const css of ['.payment-overlay.show', '.payment-adjustment-field', '.payment-change-row', '.manager-approval-fields', '.payment-confirm:disabled']) {
  requireText(posCss, css, `تنسيق نافذة التحصيل مفقود: ${css}`);
}
if (!html.includes("data-type=\"ديليفري\"") || !html.includes("order.type==='ديليفري'?'توصيل'")) {
  throw new Error('يجب أن تظل قيمة النوع الداخلية المتوافقة مع الخادم محفوظة مع تسمية محلية موحدة');
}
for (const counterId of ['counterOrders', 'counterReady', 'counterSales']) {
  requireText(html, `id="${counterId}"`, `عداد نقطة البيع ${counterId} غير موجود`);
}
if (!html.includes('/pos-retry.js') || !retryScript.includes('/api/printer/orders/')) {
  throw new Error('تدفق إعادة محاولة الإيصال غير مرتبط بالواجهة');
}
if ((html.match(/class="action-main"/g) || []).length !== 1 || html.includes('class="action-secondary"')) {
  throw new Error('يجب أن تحتوي شاشة الكاشير على زر إجراء أساسي واحد دون أزرار دفع مكررة');
}

for (const [, script] of scripts) new Function(script);
new Function(retryScript);

const currencyContext = {
  window: { dispatchEvent() {} },
  document: {
    addEventListener() {},
    documentElement: { dataset: {} },
    querySelectorAll: () => [],
    createTreeWalker: () => ({ nextNode: () => null }),
    body: {}
  },
  NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
  localStorage: { setItem() {} },
  CustomEvent: class CustomEvent {},
  fetch: async () => ({ ok: true, json: async () => ({ ok: true, currency: 'USD', usd_rate: 15000, eur_rate: 17000 }) })
};
runInNewContext(currencyScript, currencyContext);
await currencyContext.window.CAESARCurrency.set('USD', { usd_rate: 15000, eur_rate: 17000 });
const converted = currencyContext.window.CAESARCurrency.money(150000);
if (!converted.includes('$') || !converted.includes('١٠')) {
  throw new Error(`تحويل العملة في لوحة المدير غير صحيح: ${converted}`);
}

console.log('الواجهة سليمة؛ التخطيط المتجاوب والقفل والطباعة ومسارات API وتحويل العملة تحققت.');
