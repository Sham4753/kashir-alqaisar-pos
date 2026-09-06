"""CAESAR POS native-style offline desktop launcher."""
from __future__ import annotations
import socket
import threading
import time
import os
import sys
import webview

from app import server

HOST = "127.0.0.1"
PORT = int(server.os.environ.get("CAESAR_PORT", "8080"))
URL = f"http://{HOST}:{PORT}/"


def wait_for_server(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_server() -> None:
    server.start_flask()


def main() -> None:
    # Optional bundled fixed WebView2 runtime for fully offline Windows machines.
    if getattr(sys, "frozen", False):
        fixed_runtime = os.path.join(getattr(sys, "_MEIPASS", ""), "WebView2Runtime")
        if os.path.isdir(fixed_runtime):
            os.environ.setdefault("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", fixed_runtime)
    worker = threading.Thread(target=run_server, name="caesar-flask", daemon=True)
    worker.start()
    if not wait_for_server():
        raise RuntimeError("CAESAR local server did not start on 127.0.0.1:8080")
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
    main()
