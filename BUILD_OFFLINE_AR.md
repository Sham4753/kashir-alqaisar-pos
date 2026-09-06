# بناء CAESAR POS كملف EXE واحد دون إنترنت

## المتطلبات المحلية قبل البناء

ضع الملفات التالية داخل مجلد المشروع قبل تشغيل `Setup_CAESAR_OneFile.bat`:

- `python.exe` وبيئة Python المضمنة الموجودة في الحزمة.
- مجلد `offline_wheels` ويحتوي ملفات wheel الخاصة بـ `pyinstaller` و`pywebview` واعتمادياتهما، لأن السكربت لا يستخدم الإنترنت ولا ينزّل أي حزمة.
- مجلد `WebView2Runtime` يحتوي نسخة Fixed WebView2 Runtime المتوافقة مع Windows x64. يجب أن تكون النسخة مفكوكة داخل هذا المجلد، وليس ملف مثبت يحتاج تنزيلًا.

## البناء

شغّل:

```bat
Setup_CAESAR_OneFile.bat
```

أو من PowerShell:

```powershell
.\Setup_CAESAR_OneFile.ps1 -Wheelhouse .\offline_wheels -WebView2Runtime .\WebView2Runtime
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
