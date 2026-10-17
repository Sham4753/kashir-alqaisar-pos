# تقرير الفحص المكتبي — CAESAR POS

**تاريخ الفحص:** 2026-09-09 22:56 (+03:00)  
**النطاق:** الحزمة المصححة `CAESAR_POS_Production_v6`، مع التركيز على التشغيل المحلي، الطباعة، الإعدادات، وبناء PyInstaller.  
**نوع الفحص:** Static Code Analysis؛ أي فحص الملفات دون تشغيل التطبيق على Windows أو إرسال أوامر فعلية إلى طابعة.

## الحكم التنفيذي

بعد الفحص وإزالة بقايا مسار التحديث الخارجي، أصبحت مسارات التطبيق التشغيلية **محلية بالكامل من ناحية الاتصال بالإنترنت**. واجهات HTML تستخدم طلبات same-origin إلى خادم CAESAR المحلي، ولا تحتوي على مصادر JavaScript أو CSS من CDN. مسار الطابعة الشبكية يستخدم اتصال TCP اختياريًا إلى عنوان الطابعة الذي يدخله المستخدم، وليس إلى خدمة إنترنت.

اجتازت ملفات Python المستهدفة فحص الصياغة، واجتازت JavaScript المضمنة في `settings.html` و`printer_settings.html` فحص Node.js. كما اجتازت واجهة manifest فحص JSON.

مراجعة الطباعة وإعداداتها سليمة من ناحية الصياغة والربط العام. الدالة المركزية تحفظ إعدادات العرض والقص وتستخدمها في إخراج ESC/POS raster العربي. صفحة الإعدادات العامة تعرض ملخصًا وتفتح صفحة `printer_settings.html` باعتبارها النموذج المركزي لإعدادات الطابعة، وهذا يتوافق مع وصف الواجهة.

مسار البناء صحيح من حيث استدعاء PyInstaller النهائي. أضيفت إليه بوابات تمنع البناء عند فقدان `python.exe` أو `python312.dll` أو `python312.zip` أو `app/server.py`. كما أزيل fallback الذي كان يسمح باستخدام `python.exe` من `PATH`، لأن ذلك يضعف قابلية إعادة الإنتاج وقد يستدعي بيئة خارجية غير مقصودة.

## ملخص النتائج

| المجال | النتيجة | الدليل |
|---|---|---|
| التشغيل دون إنترنت | ناجح بعد الإصلاح | لا توجد روابط CDN أو استدعاءات HTTP خارجية في التطبيق، وأزيلت بقايا GitHub updater. |
| JavaScript في `settings.html` | ناجح | `node --check` نجح؛ 11 سطرًا مستخرجًا، 7,534 بايت. |
| JavaScript في `printer_settings.html` | ناجح | `node --check` نجح؛ 352 سطرًا مستخرجًا، 31,485 بايت. |
| Python | ناجح | `py_compile` نجح لـ `server.py` و`permissions.py` و`caesar_desktop.py` و`generate_license.py`. |
| JSON | ناجح | `manifest.webmanifest` اجتاز `json.tool`. |
| إعدادات الطباعة | ناجح | مفاتيح العرض والخط والقص والقالب موجودة في مسار الحفظ والتطبيع والإخراج. |
| سكريبت البناء | ناجح مع تحسينات | `Build_CAESAR_OneFile.bat` يستدعي PowerShell، وPowerShell يبني `--onefile --windowed` عبر `python -m PyInstaller`. |
| تشغيل Windows الفعلي | غير مختبر هنا | بيئة الفحص الحالية Linux؛ يلزم اختبار Windows نهائي. |

## أولًا: تدقيق الأوفلاين

### المسارات المحلية

طلبات الواجهة تستخدم مسارات مثل `/api/settings/restaurant` و`/api/printer/settings` و`/api/orders`. هذه المسارات تعود إلى خادم Flask المحلي الذي يشغله التطبيق. لم يظهر أي `fetch()` بعنوان `http://` أو `https://` خارجي.

الأصول المضمنة في صفحات HTML محلية، ومنها `tailwind.css` و`design-system.css` و`design-system.js` و`currency-manager.js` وخطوط Tajawal المحلية. لم تظهر علامات `script` أو `link` مرتبطة بـ CDN أو Google Fonts أو `unpkg` أو `jsDelivr`.

### ما تم إصلاحه

كان `server.py` يحتوي على متغير `BASE_URL` يشير إلى GitHub، مع استيراد `urllib.request` وقائمة ملفات تحديث عن بعد. ورغم أن الدالة الحالية لم تكن تنفذ اتصالًا فعليًا، فإن وجود هذا الأثر يمنع إعلان الأوفلاين الكامل من منظور التدقيق الساكن. أزيلت هذه البقايا، وأصبح `/api/check-update` يعيد حالة الإصدار المحلية فقط.

كذلك كان سكريبت البناء يستخدم `PATH` كخطة بديلة عند غياب Python المضمن. أزيل هذا السلوك، وأصبح غياب runtime المضمن يؤدي إلى إيقاف البناء برسالة واضحة.

### حدود معنى “أوفلاين”

يدعم التطبيق الطباعة إلى طابعة شبكة عبر `socket.create_connection` عندما يختار المستخدم `connection_mode=network` ويدخل عنوانًا ومنفذًا. هذا اتصال محلي اختياري إلى شبكة المطعم، وليس اتصالًا بخادم خارجي. كما تسمح إعدادات الفاتورة بحفظ روابط Facebook وInstagram وWhatsApp، لكنها تُحفظ وتُطبع كنص ولا يجري التطبيق طلبًا إليها.

يوجد `WebView2Runtime` كاعتماد Windows اختياري في البناء. إذا لم يكن موجودًا داخل الحزمة، يحذر السكريبت من أن الجهاز سيحتاج WebView2 مثبتًا محليًا. هذا ليس رابطًا خارجيًا داخل التطبيق، لكنه شرط تشغيل Windows يجب تغطيته في اختبار القبول النهائي.

## ثانيًا: الطباعة والإعدادات

### سلامة مسار الطباعة

الدالة `render_escpos_raster_payload_for_printer` تبني الصورة العربية raster ثم تستبدل ذيل القص الافتراضي بأمر القص الناتج عن `escpos_cut_bytes`. هذا يربط إعدادات `cut_enabled` و`cut_mode` و`feed_before_cut` بالمخرجات الفعلية.

المسار الشبكي يستدعي `submit_network_raw_print`، بينما مسار Windows يستدعي `submit_silent_thermal_print` ثم `submit_raw_windows_bytes`. أوامر فتح درج النقد تمر عبر `open_cash_drawer_via_printer` وتُحجب خارج Windows برسالة واضحة بدل محاولة استيراد واجهات Windows.

### توحيد الإعدادات

يقبل مسار `/api/printer/settings` القيم التالية ويطبعها أو يطبع النسخة المطَبَّعة منها:

| الفئة | المفاتيح أو القيود |
|---|---|
| الورق | `paper_width` بقيم 58 أو 80 أو 112، والاتجاه يُحفظ كـ `portrait` أو `landscape`؛ رول ESC/POS يبقى طوليًا آمنًا. |
| الخط | `font_size` و`receipt_font_scale` بقيم `small` أو `medium` أو `large`. |
| القص | `cut_enabled`، و`cut_mode` بقيم `full` أو `partial`، و`feed_before_cut` بين 0 و10. |
| التصميم | `receipt_alignment` و`receipt_divider` و`receipt_density` بقيم محصورة. |
| الشعار | `logo_size` و`logo_alignment`، مع التحقق من صورة `data:image/` وحجمها. |
| القالب | `receipt_layout` يمر عبر `is_valid_receipt_layout` ويُرفض عند وجود ترتيب غير صالح. |
| الروابط النصية | `social_facebook` و`social_instagram` و`social_whatsapp` تُحفظ كنص بعد تحقق الصيغة، ولا تُجلب عبر الشبكة. |

صفحة `settings.html` لا تكرر نموذج الطابعة؛ بل تعرض ملخصًا وتحوّل المستخدم إلى `printer_settings.html`. هذه الصفحة الأخيرة تحتوي الحقول الفعلية، وتحمّل الإعدادات من `/api/printer/settings` وتحفظها في المسار نفسه. لذلك لا توجد نسختان متنافستان من إعدادات الطباعة.

### فحوص الصياغة

تم استخراج JavaScript المضمن من الصفحتين وتشغيل `node --check` عليهما، ونجح الفحص في الحالتين. كما تم تشغيل `py_compile` على ملفات Python الأساسية، ونجح دون أخطاء Syntax.

## ثالثًا: مراجعة بناء PyInstaller

الملف `Build_CAESAR_OneFile.bat` هو wrapper مناسب؛ يتحقق من وجود `Setup_CAESAR_OneFile.ps1` وملفات runtime الأساسية و`app/server.py`، ثم يستدعي PowerShell بوضع غير تفاعلي.

الأمر النهائي في PowerShell يُبنى كالتالي:

```text
python -m PyInstaller --noconfirm --clean --onefile --windowed
  --name CAESAR_POS
  --icon app\caesar_icon.ico
  --distpath dist --workpath build --specpath build
  --add-data app;app
  [--add-data WebView2Runtime;WebView2Runtime عند وجوده]
  [--add-data ملفات الترخيص عند وجودها]
  --hidden-import app.server
  --hidden-import app.permissions
  --collect-all webview
  caesar_desktop.py
```

كما يتأكد السكريبت قبل البناء من وجود الحزم المضمنة ويستخدم `pip --no-index --find-links offline_wheels` فقط عند وجود حزمة مفقودة فعلًا. لا يسمح هذا المسار بالتثبيت من الإنترنت.

## الملفات التي تغيرت أثناء المعالجة

تم تعديل `app/server.py` لإزالة مسار التحديث الخارجي غير المستخدم، وتعديل `Setup_CAESAR_OneFile.ps1` لإلزام runtime المضمن، وتعديل `Build_CAESAR_OneFile.bat` لإضافة فحص مسبق للملفات الحرجة. لم تُجرَ تغييرات وظيفية على خوارزمية الطباعة؛ اقتصرت المراجعة عليها على التحقق من الصياغة والربط، مع توثيق الاتساق بين الواجهة والخادم.

## التحقق النهائي المطلوب على Windows

يبقى الاختبار التشغيلي النهائي خارج نطاق Static Analysis. يجب فك ضغط الحزمة، تشغيل `Build_CAESAR_OneFile.bat` على جهاز Windows دون اتصال بالإنترنت، والتأكد من إنشاء `dist\CAESAR_POS.exe`. بعد ذلك يجب تشغيل التطبيق، حفظ إعدادات الطابعة، تنفيذ طباعة تجريبية، واختبار القص ودرج النقدية مع الجهاز الفعلي.

## References

[1]: https://pyinstaller.org/en/stable/usage.html "PyInstaller usage documentation"
[2]: https://docs.python.org/3/library/urllib.request.html "Python urllib.request documentation"
[3]: https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API "MDN Fetch API documentation"
