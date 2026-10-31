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
const match = html.match(/<script>([\s\S]*?)<\/script>/i);

if (!match) throw new Error('لم يتم العثور على JavaScript لواجهة نقطة البيع');
if (html.includes('window.print') || html.includes('window.open')) {
  throw new Error('لا يجب أن تستدعي واجهة الإيصال نافذة أو مربع طباعة المتصفح');
}
if (!html.includes('id="lockButton"') || !html.includes('/api/auth/unlock')) {
  throw new Error('قفل الشاشة أو فك القفل المقيّد بالمدير غير موجود في الواجهة');
}
if (!html.includes('/api/orders') || !html.includes('printState')) {
  throw new Error('تدفق الدفع أو حالة الإرسال إلى الطابعة غير مكتمل في الواجهة');
}
for (const guidance of [
  'اضغط على البطاقة للإضافة السريعة',
  'يتحكم بمسار التشغيل',
  'اختر قبل التأكيد',
  'ابحث باسم الصنف أو القسم',
  'السلة فارغة. اختر المنتجات لبدء طلب جديد.',
  'سيُرسل الإيصال إلى الطابعة المحلية دون فتح مربع طباعة.'
]) {
  if (html.includes(guidance)) throw new Error(`نص إرشادي قديم ما زال ظاهرًا في شاشة الكاشير: ${guidance}`);
}
if (!html.includes('placeholder="بحث"') || !html.includes('id="printState" aria-live="polite"></div>')) {
  throw new Error('اختصار حقل البحث أو عرض حالة الطباعة عند الحاجة غير مكتمل');
}
for (const counterId of ['counterOrders', 'counterReady', 'counterSales']) {
  if (!html.includes(`id="${counterId}"`)) throw new Error(`عداد نقطة البيع ${counterId} غير موجود في القالب`);
}
if (!html.includes('/api/dashboard/counters') || !posCss.includes('.counter-strip { display: grid !important;')) {
  throw new Error('تحميل عدادات نقطة البيع أو قاعدة إبقائها ظاهرة غير موجودة');
}
if (!html.includes('/pos-retry.js') || !retryScript.includes('/api/printer/orders/')) {
  throw new Error('تدفق إعادة محاولة الإيصال غير مرتبط بالواجهة');
}

new Function(match[1]);
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

console.log('الواجهة سليمة؛ تحويل العملة والخصائص الأساسية تحققت.');
