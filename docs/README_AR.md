# فهرس وثائق كاشير قيصر POS

هذا الفهرس ينظم وثائق Markdown الموجودة في جذر المستودع. ابدأ بالمراجع الحالية، ثم انتقل إلى دليل المجال المطلوب. تقارير التدقيق والتسليم القديمة تحفظ سياقًا تاريخيًا ولا تحل محل مصدر حقيقة البرنامج الحالي: `app/server.py` و`app/permissions.py`.

> ملفات runtime في جذر المستودع، ومنها Python المضمن ومكتبته وملفات التشغيل، مقصودة ضمن حزمة Windows المحمولة. لا تحذفها أو تستبعدها لمجرد حجمها؛ تحقق من دورها في التشغيل قبل أي تغيير.

## اقرأ أولًا

- [README_AR.md](../README_AR.md) — دليل التشغيل للمستخدم وإعداد الحزمة.
- [AGENTS.md](../AGENTS.md) — نقطة البدء الموحدة وتعليمات وكلاء الكود.
- [HANDOFF.md](../HANDOFF.md) — موجز حالة العمل الحالي، الفحوص وما بقي.
- [AI_HANDOFF_AR.md](../AI_HANDOFF_AR.md) — مرجع البنية التقنية ومسؤوليات النظام.
- [CANONICAL_RUNTIME_AR.md](../CANONICAL_RUNTIME_AR.md) — نقطة تشغيل Windows والفصل بين المصدر وVault.

## التشغيل والتسليم والنشر

- [دليل_التشغيل_الكامل_AR.md](../دليل_التشغيل_الكامل_AR.md) — خطوات التشغيل والاستعداد للاستخدام.
- [تشغيل_من_USB_AR.md](../تشغيل_من_USB_AR.md) — تشغيل الحزمة من وسيط USB.
- [BUILD_OFFLINE_AR.md](../BUILD_OFFLINE_AR.md) — بناء الحزمة دون اتصال.
- [RELEASE_UPDATE_GUIDE_AR.md](../RELEASE_UPDATE_GUIDE_AR.md) — تجهيز تحديث GitHub وتثبيته يدويًا على جهاز العميل.
- [RUNTIME_ENTRYPOINT_AR.md](../RUNTIME_ENTRYPOINT_AR.md) — نقاط دخول التشغيل.
- [RUNTIME_REPAIR_VERIFICATION_AR.md](../RUNTIME_REPAIR_VERIFICATION_AR.md) — تحقق إصلاحات runtime.
- [INSTALLER_GUIDE_AR.md](../INSTALLER_GUIDE_AR.md) — إرشادات التثبيت.
- [ONEFOLDER_DEPLOYMENT_AR.md](../ONEFOLDER_DEPLOYMENT_AR.md) — تسليم One-Folder.
- [FULL_PACKAGE_MANIFEST_AR.md](../FULL_PACKAGE_MANIFEST_AR.md) — جرد مكونات الحزمة.
- [COMMERCIAL_DELIVERY_GUIDE_AR.md](../COMMERCIAL_DELIVERY_GUIDE_AR.md) — إرشادات التسليم التجاري.
- [RELEASE_UPDATE_GUIDE_AR.md](../RELEASE_UPDATE_GUIDE_AR.md) و[UPGRADE_NOTES_AR.md](../UPGRADE_NOTES_AR.md) — تحديثات وترقيات.
- [RELEASE_PATCH_NOTES_AR.md](../RELEASE_PATCH_NOTES_AR.md) و[PRODUCTION_RELEASE_NOTE.md](../PRODUCTION_RELEASE_NOTE.md) — ملاحظات الإصدار.
- [MERGE_NOTES.md](../MERGE_NOTES.md)، [plan.md](../plan.md)، [TODO.md](../TODO.md) — ملاحظات دمج وخطط/مهام؛ تحقق من حداثتها قبل اعتمادها.

## الطباعة والصلاحيات والتشغيل اليومي

- [دليل_الطباعة_والصلاحيات_AR.md](../دليل_الطباعة_والصلاحيات_AR.md) — مرجع عملي للطباعة والأدوار.
- [مصفوفة_الصلاحيات_AR.md](../مصفوفة_الصلاحيات_AR.md) — ملخص صلاحيات الصفحات والعمليات؛ المصدر التنفيذي هو `app/permissions.py`.
- [PRINTER_COMPATIBILITY_AR.md](../PRINTER_COMPATIBILITY_AR.md) — توافق الطابعات.
- [PRINTER_ORIENTATION_AR.md](../PRINTER_ORIENTATION_AR.md) — اتجاه ومقاسات الطباعة.
- [PRINTER_MAINTENANCE_AR.md](../PRINTER_MAINTENANCE_AR.md) و[PRINTER_REPAIR_AR.md](../PRINTER_REPAIR_AR.md) — صيانة الطباعة وتشخيصها.
- [DESIGN_SYSTEM_REPAIR_REPORT_AR.md](../DESIGN_SYSTEM_REPAIR_REPORT_AR.md) — تقرير تاريخي لإصلاحات التصميم.
- [SQLITE_MIGRATION_NOTE_AR.md](../SQLITE_MIGRATION_NOTE_AR.md) — ملاحظات ترحيل التخزين إلى SQLite.

## الأمن والترخيص والبيانات

- [LICENSE_ED25519_AR.md](LICENSE_ED25519_AR.md) — مرجع الترخيص الحالي بمفتاح مورّد Ed25519.
- [LICENSE_SECRET_SETUP_AR.md](../LICENSE_SECRET_SETUP_AR.md) — تنبيه أرشيفي يوضح أن تعليمات HMAC القديمة لم تعد مستخدمة.
- [SECURITY_QUALITY_REVIEW_AR.md](../SECURITY_QUALITY_REVIEW_AR.md) — مراجعة جودة وأمن تاريخية.
- [SECURITY_REMEDIATION_REPORT_AR.md](../SECURITY_REMEDIATION_REPORT_AR.md) و[SECURITY_REPAIR_REPORT_AR.md](../SECURITY_REPAIR_REPORT_AR.md) — تقارير معالجة وإصلاح أمنية.
- [CANONICAL_RUNTIME_AR.md](../CANONICAL_RUNTIME_AR.md) — مرجع حماية Vault وفصلها عن Git.

## التقارير والتدقيق التاريخي

الوثائق التالية تسجل مراجعات أو نتائج مرتبطة بلحظات/نسخ سابقة. اقرأ تاريخها ونطاقها، ولا تعامل أرقام الاختبارات أو الاستنتاجات القديمة على أنها الحالة الحالية:

- [ACCEPTANCE_REPORT_AR.md](../ACCEPTANCE_REPORT_AR.md) و[DELIVERY_QA_REPORT_AR.md](../DELIVERY_QA_REPORT_AR.md) و[تقرير_التحقق_والإصدار_AR.md](../تقرير_التحقق_والإصدار_AR.md) — قبول وتسليم وتحقق إصدار.
- [DELIVERY_FIXED_NOTE_AR.md](../DELIVERY_FIXED_NOTE_AR.md) و[CAESAR_POS_Production_v6_FIX_REPORT_AR.md](../CAESAR_POS_Production_v6_FIX_REPORT_AR.md) — ملاحظات إصلاح وتسليم.
- [CAESAR_POS_Production_Review_AR.md](../CAESAR_POS_Production_Review_AR.md)، [COMPREHENSIVE_PREFLIGHT_GUIDE_AR.md](../COMPREHENSIVE_PREFLIGHT_GUIDE_AR.md)، [PREFLIGHT_FINAL_REPORT_AR.md](../PREFLIGHT_FINAL_REPORT_AR.md) — مراجعة وفحوص ما قبل التشغيل.
- [FULL_CODE_AUDIT_AR.md](../FULL_CODE_AUDIT_AR.md)، [FIXES_AND_AUDIT_AR.md](../FIXES_AND_AUDIT_AR.md)، [STATIC_CODE_ANALYSIS_AR.md](../STATIC_CODE_ANALYSIS_AR.md) — تدقيق وتحليل الشيفرة.
- [POS_AUDIT_AND_REDESIGN_AR.md](../POS_AUDIT_AND_REDESIGN_AR.md)، [STABILITY_AUDIT_AR.md](../STABILITY_AUDIT_AR.md)، [PERFORMANCE_FIX_REPORT_AR.md](../PERFORMANCE_FIX_REPORT_AR.md) — إعادة تصميم واستقرار وأداء.
- [ERROR_500_DIAGNOSIS_AR.md](../ERROR_500_DIAGNOSIS_AR.md) — تشخيص تاريخي لأخطاء الخادم.
- [تقرير_المقارنة_والدمج_CAESAR.md](../تقرير_المقارنة_والدمج_CAESAR.md) — مقارنة ودمج تاريخيان.

## عند التعارض أو التقادم

اعتمد السلوك الموجود في المصدر الحالي والاختبارات ذات الصلة، ثم حدّث الوثيقة المناسبة بدل إضافة نسخة موازية. معلومات التقارير القديمة ليست ضمانًا بأن الوضع الحالي أو الاختبارات الحالية مماثلة لها. لا ترفع إلى أي وثيقة عامة بيانات مطعم أو مسارات شخصية أو معرّفات أجهزة/تراخيص أو محتوى أسرار.
