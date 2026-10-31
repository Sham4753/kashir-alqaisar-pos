# بناء CAESAR POS على Windows

## المتطلبات

يستخدم البناء Python 3.12 وبيئة التشغيل والمكتبات المحمولة في `Lib/site-packages`. تتضمن الحزمة PyInstaller وFlask وPyWebView و`cryptography`، وامتداد CFFI الأصلي `_cffi_backend.cp312-win_amd64.pyd` المطابق لـWindows x64 وCPython 3.12. يسجل `embedded_packages_manifest.json` تفاصيل المكتبات؛ لا يعتمد البناء على Python العام عند اكتمال runtime.

يجب إنشاء مفاتيح المورّد مرة واحدة قبل بناء نسخة توزيع: المفتاح العام Ed25519 في `app\license_public_key.pem`، والمفتاح الخاص المشفّر وعبارة مروره خارج المستودع. راجع [دليل الترخيص](docs/LICENSE_ED25519_AR.md). يرفض البناء غياب المفتاح العام أو ملف PEM غير صالح أو غير Ed25519، ويفحص شجرة `app` وملف OneFolder كاملًا لمنع ضم بيانات أو تراخيص أو مفاتيح خاصة.

## الاختبارات

من PowerShell في جذر المستودع:

```powershell
$env:PYTHONPATH = "$PWD\Lib\site-packages;$PWD\app;$PWD"
.\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\python.exe -m unittest discover -s tools\tests -v
node tests\verify_frontend.mjs
```

يجب أن يجتاز المصدر Windows CI قبل النشر. نجاح اختبارات Linux أو ZIP لا يثبت نجاح PyInstaller أو تشغيل Windows.

## بناء النسخة وحزم التسليم

```powershell
.\Setup_CAESAR_OneFile.ps1
```

ينتج البناء مجلد OneFolder، ويتحقق من المفتاح العام ووجود شاشة الحسابات وتخطيط الواجهة وخلو الحزمة من بيانات العميل، ثم ينشئ:

```text
dist\CAESAR_POS\CAESAR_POS.exe
CAESAR_POS_OneFolder_Commercial_v4.0.1.zip
dist\CAESAR_POS_Update_v4.0.1.zip
```

يقرأ رقم الإصدار من `CURRENT_VERSION` في `app\server.py`. ZIP التجاري لعميل جديد، ويبدأ من دون رخصة. ZIP التحديث لتثبيت قائم فقط. يسمح التحديث بأصول التطبيق الثابتة المحددة في `app/factory_data.json` و`app/license_public_key.pem`، وبملف `Python.Runtime.deps.json` المحدد لمسارات pythonnet عند الحاجة؛ لا يُسمح بأي JSON آخر. ويستبعد بيانات المطعم وVault وقواعد SQLite وملفات WAL/SHM والسجلات والتراخيص والأسرار ومولّد التراخيص وحاويات الشهادات الخاصة.

## تسليم تحديث العميل عبر GitHub

ارفع `CAESAR_POS_Update_v*.zip` كأصل GitHub Release وأرسل رابط تنزيل الأصل المباشر. لا ترسل رابط المستودع أو أرشيف المصدر. الرابط لا يثبت التحديث تلقائيًا. يفك العميل ضغط ZIP ويشغّل `Apply_CAESAR_Update.bat` ثم يحدد مجلد التثبيت الذي يحتوي `CAESAR_POS.exe`.

يستبدل المُحدّث الملفات الواردة فقط، ويحتفظ بنسخ مؤقتة للملفات المستبدلة ليتراجع عند الفشل. لا يلمس `CAESAR_Vault` أو الترخيص المحلي ولا يحذف ملفات أخرى. يبدأ العميل التطبيق يدويًا بعد رسالة النجاح. خذ نسخة احتياطية واختبر الحزمة على Windows قبل إرسالها.
