Option Explicit
' نسخة USB من الإطلاق الرسمي: تشغّل Start.bat (يوقف أي سيرفر قديم عالق على
' المنفذ 8080 أولاً، ثم يشغّل السورس الحالي، ثم يفتح نافذة التطبيق الوحيدة) بشكل مخفي بدون
' نافذة سوداء. لا تستخدم أي ملف exe قديم — انظر RUNTIME_ENTRYPOINT_AR.md.
Dim shell, fso, root, starter
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
starter = fso.BuildPath(root, "Start.bat")
shell.CurrentDirectory = root
If fso.FileExists(starter) Then
  shell.Run """" & starter & """", 0, False
Else
  shell.Popup "ملف Start.bat مفقود. فك ضغط الحزمة كاملة ثم أعد المحاولة.", 6, "كاشير قيصر قيصر", 16
End If
Set fso = Nothing
Set shell = Nothing
