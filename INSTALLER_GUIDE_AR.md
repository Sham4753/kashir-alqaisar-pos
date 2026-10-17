# إعداد Installer لتوزيع CAESAR POS

يستخدم المشروع ملف Inno Setup لتغليف مجلد OneFolder كاملًا في ملف تثبيت واحد. يجب تنفيذ عملية البناء على Windows لأن Inno Setup وPyInstaller يستهدفان Windows.

## المتطلبات

ثبّت **Inno Setup** على جهاز البناء، ثم:

1. شغّل `Build_CAESAR_OneFolder.bat`.
2. تأكد من إنشاء:
   ```text
   dist\CAESAR_POS\CAESAR_POS.exe
   ```
3. افتح:
   ```text
   installer\CAESAR_POS_OneFolder.iss
   ```
4. افتح الملف باستخدام Inno Setup Compiler واضغط **Compile**.

سينتج المثبّت في:

```text
installer_output\CAESAR_POS_Installer_v6.exe
```

## ما يفعله المثبّت

ينسخ مجلد OneFolder كاملًا، بما فيه `_internal` وملفات DLL وملفات WebView2 المرفقة إن وجدت، إلى:

```text
%LOCALAPPDATA%\CAESAR POS
```

ثم ينشئ اختصارًا في قائمة Start. ويمكن اختيار إنشاء اختصار على سطح المكتب. يستخدم التثبيت صلاحيات المستخدم العادي ولا يحتاج Administrator.

## التوزيع دون إنترنت

انسخ ملف:

```text
CAESAR_POS_Installer_v6.exe
```

إلى الجهاز الهدف عبر USB. لا يحتاج الجهاز إلى إنترنت إذا كانت WebView2 Runtime مضمّنة داخل مجلد OneFolder. إذا لم تكن مضمّنة، يجب أن يكون WebView2 Runtime مثبتًا مسبقًا على Windows.

## الترخيص والبيانات

لا تضع `generate_license.py` داخل Installer التجاري. احتفظ به على جهاز المورّد فقط. يبقى `CAESAR_Vault` خارج مجلد تثبيت البرنامج ولا يحذفه إلغاء التثبيت. هذا يحمي بيانات العميل عند تحديث البرنامج أو إزالته.

## التحديث

عند إصدار نسخة جديدة، استخدم Installer جديدًا بنفس `AppId`. سيحدّث Inno Setup ملفات البرنامج مع إبقاء بيانات `CAESAR_Vault` خارج مجلد التثبيت.

## ملاحظة أمنية

التثبيت لا يمنع نسخ الملفات من جهاز يملك المستخدم صلاحية الوصول إليه. حماية التشغيل تعتمد على نظام الترخيص HWID الموجود في التطبيق، بينما Installer مهمته تسهيل النسخ الصحيح والكامل لمجلد OneFolder وإنشاء الاختصارات.
