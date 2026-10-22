# بناء CAESAR POS كملف EXE واحد دون إنترنت

## المتطلبات المحلية قبل البناء

تتضمن الحزمة نسخة Python 3.12 محمولة ومكتبات البناء والتشغيل داخل `Lib/site-packages`، ومنها `PyInstaller` و`pywebview` و`Flask`. يتضمن `offline_wheels` أيضاً wheel متوافقاً مع Python 3.12 على Windows x64 لـ CFFI وملحقه `pycparser`؛ يستخدمهما سكربت البناء فقط عند غياب CFFI المضمن أو ملحقه الأصلي، دون الاتصال بالإنترنت أو تثبيت الحزم في Python العام.

قبل تشغيل البناء، تأكد من وجود:

- `python.exe` وبيئة Python المضمنة الموجودة في الحزمة.
- `Lib/site-packages` بالمحتوى المرفق.
- `app` و`caesar_desktop.py` و`app\caesar_icon.ico`.
- `WebView2Runtime` اختياريًا؛ وجوده يتيح تشغيل التطبيق على أجهزة لا تحتوي WebView2 مسبقًا.

إذا كان أحد الاستيرادات المطلوبة مفقودًا فعلًا، يتوقف السكربت برسالة واضحة ويبحث فقط عن wheel المطابق لذلك الاعتماد داخل `offline_wheels`. لا يتم طلب تثبيت أو استخدام `pip` عند اكتمال المكتبات المضمنة، ولا يُستخدم الإنترنت كمسار خفي.

## البناء

شغّل:

```bat
Setup_CAESAR_OneFile.bat
```

أو من PowerShell:

```powershell
.\Setup_CAESAR_OneFile.ps1
```

يعرض السكربت أولًا حالة الاعتمادات. عند اكتمالها ستظهر رسالة شبيهة بـ:

```text
Embedded Python environment is complete; skipping pip and offline_wheels installation.
```

ينتج السكربت:

```text
dist\CAESAR_POS.exe
dist\generate_license.py
CAESAR_POS_Commercial_v4.zip
```

## ملاحظات التشغيل

الملف التنفيذي يشغّل خادم Flask محليًا على `127.0.0.1` ثم يفتح نافذة `pywebview` باستخدام EdgeChromium. لا يفتح متصفحًا عاديًا ولا يحتاج إلى اتصال خارجي. تُحفظ بيانات المستخدم في `CAESAR_Vault` القابل للكتابة، بينما تبقى ملفات الواجهة والخادم داخل الحزمة.

وجود `WebView2Runtime` داخل الحزمة يضمن التشغيل على جهاز غير متصل بالإنترنت حتى إذا لم يكن WebView2 مثبتًا مسبقًا. إذا لم يضع الباني هذا المجلد، فلن يتمكن التطبيق من ضمان التشغيل على كل جهاز Windows؛ سيعتمد عندها على WebView2 المثبت مسبقًا دون تنزيل تلقائي.

## اختبار قبل التسليم

يجب تشغيل اختبارات المشروع أولًا من مجلد المصدر:

```bat
python.exe -m unittest discover -s tests -p "test_*.py" -v
```

ثم فحص الواجهة:

```bat
node tests\verify_frontend.mjs
```

وأخيرًا تشغيل `dist\CAESAR_POS.exe` على جهاز Windows مفصول عن الإنترنت والتحقق من الدخول، إنشاء فاتورة، العداد، التصفير، الترخيص، والنسخ الاحتياطي.

## إصلاح خطأ Embedded package missing

يستخدم `Setup_CAESAR_OneFile.ps1` الآن `python.exe` الموجود داخل مجلد الحزمة فقط، ويضيف `Lib\site-packages` إلى مسار الاستيراد صراحةً. لذلك سيتم اكتشاف Flask وPyInstaller وPyWebView حتى إذا لم يقرأ Windows ملف `python312._pth` بعد فك الضغط أو إعادة تسمية المجلد. لا يتم تشغيل pip عندما تكون الحزم المضمنة موجودة.

إذا ظهرت مشكلة جديدة، سيطبع السكربت مسار Python ومسارات الحزم المستخدمة قبل إظهار الحزمة الناقصة، بدل إعطاء تحذير عام فقط.
