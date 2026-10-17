# دليل فحص ما قبل تجميع CAESAR POS

## الملفات المضافة

يوجد الفاحص في `tools/comprehensive_preflight.py`، ويوجد حاجز البناء في `Build_CAESAR_With_Preflight.bat`. لا ينشئ حاجز البناء ملف EXE إلا إذا خرج الفاحص برمز نجاح `0`.

## التشغيل قبل البناء

من داخل مجلد المشروع شغّل:

```bat
python tools\comprehensive_preflight.py --report preflight-report.json
```

يعرض الفاحص نتيجة مستقلة لكل بند بصيغة `SUCCESS` أو `FAIL` أو `SKIP`، ويكتب تقرير JSON قابلًا للأرشفة والمراجعة.

الفحوص تشمل جرد الأصول المحلية، منع اعتماد CDN، تحليل Python وJavaScript، صلاحيات القراءة والكتابة، اختبار SQLite، وجود منطق السلة والخصم والدفع والباركود، اختبار توليد صورة ESC/POS عربية بخط Tajawal، تشغيل الخادم المحلي وفحص كل صفحات HTML ومسارات API الأساسية، ثم تشغيل اختبارات المشروع الموجودة في `tests`.

الضريبة **غير مطلوبة** في إعداد هذا النظام للسوق السورية، لذلك يسجلها الفاحص `SKIP` ولا تمنع بناء EXE. إذا احتاج إصدار مستقبلي إلى ضريبة، يمكن تفعيلها صراحةً عبر الخيار `--require-tax`.

## فحص الطابعة ودرج النقدية

لإجراء فحص اتصال طابعة شبكة ودرج نقدية عبر TCP:

```bat
python tools\comprehensive_preflight.py ^
  --printer-host 192.168.1.50 --printer-port 9100 ^
  --cash-drawer-host 192.168.1.50 --cash-drawer-port 9100 ^
  --strict-hardware --report preflight-report.json
```

يمكن استخدام متغيرات البيئة بدل تمرير الخيارات:

```bat
set CAESAR_PRINTER_HOST=192.168.1.50
set CAESAR_PRINTER_PORT=9100
set CAESAR_DRAWER_HOST=192.168.1.50
set CAESAR_DRAWER_PORT=9100
```

لطابعة USB/COM، استخدم:

```bat
set CAESAR_PRINTER_SERIAL=COM3
set CAESAR_PRINTER_BAUD=9600
python tools\comprehensive_preflight.py --strict-hardware
```

بدون `--strict-hardware` تكون أجهزة غير المهيأة `SKIP` حتى يمكن تشغيل الفحص على جهاز التطوير. في بوابة البناء المرفقة تم تفعيل `--strict-hardware`، لذلك يجب تزويد معلومات الطابعة ودرج النقدية قبل إنتاج EXE.

## ربط الفحص بالتجميع

شغّل:

```bat
Build_CAESAR_With_Preflight.bat
```

يعمل الملف بالترتيب التالي:

1. تشغيل `tools\comprehensive_preflight.py` بوضع `--strict-hardware`.
2. إيقاف العملية فورًا إذا وجد أي `FAIL` أو جهاز غير مهيأ.
3. تشغيل أول ملف بناء موجود بالترتيب: `Setup_CAESAR_OneFile.bat` ثم `Build_CAESAR_OneFile.bat` ثم `Setup_CAESAR_OneFile.ps1`.
4. إرجاع رمز خروج غير صفري عند الفشل، ما يمنع CI أو أي سكريبت أعلى منه من اعتبار البناء ناجحًا.

إذا لم يكن اسم سكريبت البناء الحالي واحدًا من هذه الأسماء، عدّل قسم البناء في `Build_CAESAR_With_Preflight.bat` فقط، ولا تضع أمر البناء قبل الفحص.

## تفسير النتائج

| الحالة | معناها | أثرها على البناء |
|---|---|---|
| `SUCCESS` | الفحص نجح | يسمح بالاستمرار |
| `FAIL` | عطل أو متطلب مفقود | يمنع إنشاء EXE |
| `SKIP` | فحص اختياري لم تُمرر له إعدادات | مسموح في الوضع العادي، وغير مسموح في بوابة `--strict-hardware` |

الفحص لا يحذف بيانات الإنتاج ولا يغيّر قاعدة بيانات العميل. اختبار الخادم يستخدم HOME مؤقتًا. أما اختبار الطباعة الفعلي عبر الشبكة أو COM فيحتاج جهاز Windows والطابعة المتصلة. فحص الصورة العربية يتأكد من أن النص لا يُرسل UTF-8 خامًا، بينما يجب إجراء طباعة اختبار فعلية للتأكد من توافق الطابعة وقص الوصل.
