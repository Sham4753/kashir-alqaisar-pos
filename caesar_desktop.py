"""CAESAR POS native-style offline desktop launcher."""
from __future__ import annotations
import socket
import threading
import time
import os
import sys
import traceback
import webview

from app import server

HOST = "127.0.0.1"
PORT = int(server.os.environ.get("CAESAR_PORT", "8080"))
URL = f"http://{HOST}:{PORT}/"

# مع --windowed لا توجد نافذة Console، فأي استثناء غير معالج كان يختفي بصمت
# ويظهر للمستخدم كـ"شاشة سوداء" أو إغلاق فوري للبرنامج دون أي رسالة. الحل:
# 1) كل الأخطاء تُكتب دائماً إلى ملف سجل بجانب الملف التنفيذي.
# 2) أي استثناء غير متوقع يُعرض كصندوق رسالة Windows حتى لو لم توجد Console.
def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_PATH = os.path.join(_app_dir(), "caesar_desktop_error.log")


def _log_error(message: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + message + "\n")
    except OSError:
        pass


def _show_fatal_error(title: str, message: str) -> None:
    _log_error(f"{title}: {message}")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
            return
        except Exception:
            pass
    # لا نملك واجهة رسائل على غير ويندوز أو إن فشل MessageBox؛ نطبع للـ stderr
    # كحل أخير (يظهر فقط إذا كانت هناك Console).
    print(f"{title}: {message}", file=sys.stderr)


def wait_for_server(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.2)
    return False


_SERVER_ERROR: list[BaseException] = []


def run_server() -> None:
    # خيط Flask يعمل كـ daemon؛ أي استثناء فيه لا يوقف العملية الرئيسية ولا
    # يظهر لأحد - فقط يسقط الخيط بصمت وتبقى wait_for_server() تنتظر حتى تنتهي
    # المهلة. نلتقط الخطأ الحقيقي هنا لعرضه بدل رسالة "لم يبدأ الخادم" العامة.
    try:
        server.start_flask()
    except BaseException as exc:  # noqa: BLE001 - نريد كل الأخطاء هنا تحديدًا
        _SERVER_ERROR.append(exc)
        _log_error("Flask server thread crashed:\n" + traceback.format_exc())


def main() -> None:
    # Optional bundled fixed WebView2 runtime for fully offline Windows machines.
    if getattr(sys, "frozen", False):
        fixed_runtime = os.path.join(getattr(sys, "_MEIPASS", ""), "WebView2Runtime")
        if os.path.isdir(fixed_runtime):
            os.environ.setdefault("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", fixed_runtime)
    worker = threading.Thread(target=run_server, name="caesar-flask", daemon=True)
    worker.start()
    if not wait_for_server():
        if _SERVER_ERROR:
            detail = "".join(
                traceback.format_exception(
                    type(_SERVER_ERROR[0]), _SERVER_ERROR[0], _SERVER_ERROR[0].__traceback__
                )
            )
        else:
            detail = (
                "لم يبدأ الخادم المحلي خلال 15 ثانية دون أي استثناء واضح.\n"
                "الأسباب الشائعة: المنفذ 8080 مستخدم من برنامج آخر، أو ملفات\n"
                "app/ لم تُنسخ بشكل صحيح مع الحزمة (راجع --add-data)."
            )
        _show_fatal_error(
            "CAESAR POS - فشل تشغيل الخادم المحلي",
            "تعذّر تشغيل خادم النظام على 127.0.0.1:8080.\n\n" + detail
            + f"\n\nراجع ملف السجل: {LOG_PATH}",
        )
        sys.exit(1)
    webview.create_window(
        "CAESAR POS",
        URL,
        width=1280,
        height=820,
        min_size=(1024, 680),
        resizable=True,
        confirm_close=True,
        # pywebview يمنع تحديد النصوص افتراضياً (text_select=False)، وهذا كان
        # يمنع نسخ/لصق رقم ومفتاح الترخيص وأي حقل آخر داخل نافذة سطح المكتب.
        text_select=True,
    )
    # نافذة أدوات المطوّر (DevTools) مطفأة نهائياً في النسخة الإنتاجية عبر
    # debug=False. هذا يُسقط فقط قائمة الفأرة اليمنى الأصلية من WebView2 (فهما
    # مرتبطتان ببعضهما في هذا الإصدار من pywebview/edgechromium ولا يمكن فصلهما).
    # لتعويض ذلك، أضفنا قائمة يمنى بديلة خفيفة (نسخ/قص/لصق/تحديد الكل) مبنية
    # بالكامل بجافاسكريبت في design-system.js تعمل على كل الشاشات والحقول -
    # راجع التعليق أعلى ذلك الملف. أما اختصارات لوحة المفاتيح (Ctrl+C/Ctrl+V/
    # Ctrl+A) فتبقى تعمل دائماً وبلا أي قيد عبر text_select=True أعلاه، بصرف
    # النظر عن قيمة debug هنا - فهي اختصارات يتعامل معها محرك المتصفح مباشرة.
    debug_mode = os.environ.get("CAESAR_WEBVIEW_DEBUG", "0") == "1"
    webview.start(gui="edgechromium", debug=debug_mode)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - آخر خط دفاع قبل الشاشة السوداء
        _show_fatal_error(
            "CAESAR POS - خطأ غير متوقع",
            "حدث خطأ أدى لإغلاق البرنامج.\n\n" + traceback.format_exc()
            + f"\n\nراجع ملف السجل: {LOG_PATH}",
        )
        sys.exit(1)
