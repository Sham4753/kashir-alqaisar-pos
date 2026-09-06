Option Explicit
' نقطة الإطلاق الرسمية لاختصار سطح المكتب: تشغّل Start.bat (الفحص الكامل +
' تنظيف أي عملية سيرفر عالقة من تشغيل سابق + فتح نافذة التطبيق تلقائياً) بشكل
' مخفي تماماً بدون أي نافذة سوداء وامضة، مع إبقاء نافذة المتصفح ظاهرة كالمعتاد.
Dim shell, fso, root, starter
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
starter = fso.BuildPath(root, "Start.bat")
shell.CurrentDirectory = root
If fso.FileExists(starter) Then
  shell.Run """" & starter & """", 0, False
Else
  MsgBox "ملف التشغيل Start.bat مفقود. تأكد من فك الحزمة كاملة داخل مجلد كاشير قيصر قيصر.", vbCritical, "كاشير قيصر قيصر"
End If
