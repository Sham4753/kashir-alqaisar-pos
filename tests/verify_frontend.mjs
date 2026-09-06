import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const indexPath = resolve(process.cwd(), 'app', 'index.html');
const html = readFileSync(indexPath, 'utf8');
const retryPath = resolve(process.cwd(), 'app', 'pos-retry.js');
const retryScript = readFileSync(retryPath, 'utf8');
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
if (!html.includes('/pos-retry.js') || !retryScript.includes('/api/printer/orders/')) {
  throw new Error('تدفق إعادة محاولة الإيصال غير مرتبط بالواجهة');
}

new Function(match[1]);
new Function(retryScript);
console.log('واجهة نقطة البيع: صياغة JavaScript سليمة ولا توجد طباعة متصفح.');
