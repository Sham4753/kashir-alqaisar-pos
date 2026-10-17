#!/usr/bin/env python3
"""Comprehensive offline POS pre-flight gate.

Examples:
  python tools/comprehensive_preflight.py
  python tools/comprehensive_preflight.py --printer-host 192.168.1.50 --printer-port 9100 --cash-drawer-host 192.168.1.50 --cash-drawer-port 9100 --strict-hardware
  python tools/comprehensive_preflight.py --report preflight-report.json

The command exits 0 only when every required check is SUCCESS. Hardware checks are
reported as SKIP when no device endpoint is supplied; use --strict-hardware in the
build gate to make missing hardware configuration a failure.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Result:
    section: str
    name: str
    status: str
    detail: str


class Suite:
    def __init__(self, root: Path, args: argparse.Namespace):
        self.root = root.resolve()
        self.app = self.root / "app"
        self.args = args
        self.results: list[Result] = []

    def add(self, section: str, name: str, status: str, detail: str) -> None:
        self.results.append(Result(section, name, status, detail.replace("\n", " ")[:800]))
        print(f"{status:<7} [{section}] {name}: {detail}")

    def success(self, section: str, name: str, detail: str) -> None:
        self.add(section, name, "SUCCESS", detail)

    def fail(self, section: str, name: str, detail: str) -> None:
        self.add(section, name, "FAIL", detail)

    def skip(self, section: str, name: str, detail: str) -> None:
        self.add(section, name, "SKIP", detail)

    def run(self) -> int:
        self.static_files()
        self.python_and_javascript()
        self.offline_permissions_and_database()
        self.core_logic_static()
        self.escpos_readiness()
        self.hardware()
        self.local_http()
        self.unit_tests()
        self.write_report()
        failures = sum(r.status == "FAIL" for r in self.results)
        print(f"\nSUMMARY: SUCCESS={sum(r.status == 'SUCCESS' for r in self.results)} "
              f"FAIL={failures} SKIP={sum(r.status == 'SKIP' for r in self.results)}")
        return 1 if failures else 0

    def static_files(self) -> None:
        required = [
            self.app / "server.py", self.app / "index.html", self.app / "login.html",
            self.app / "settings.html", self.app / "shift.html", self.app / "tailwind.css",
            self.app / "design-system.css", self.app / "design-system.js",
            self.app / "fonts" / "Tajawal-Regular.ttf", self.app / "fonts" / "Tajawal-Bold.ttf",
        ]
        missing = [str(p.relative_to(self.root)) for p in required if not p.is_file()]
        if missing:
            self.fail("ENVIRONMENT", "Required offline assets", "Missing: " + ", ".join(missing))
        else:
            self.success("ENVIRONMENT", "Required offline assets", f"{len(required)} required files present")
        external = []
        for p in self.app.rglob("*"):
            if p.suffix.lower() not in {".html", ".css", ".js"}:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(r"(?:https?:)?//(?:unpkg|cdn\.jsdelivr|fonts\.googleapis|cdnjs)", text, re.I):
                external.append(str(p.relative_to(self.root)))
        if external:
            self.fail("ENVIRONMENT", "No required CDN assets", "External asset references: " + ", ".join(external[:8]))
        else:
            self.success("ENVIRONMENT", "No required CDN assets", "All checked UI assets are local")

    def python_and_javascript(self) -> None:
        py_files = [p for p in self.app.rglob("*.py") if "vendor" not in p.parts and "__pycache__" not in p.parts]
        bad = []
        for path in py_files:
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                bad.append(f"{path.name}: {exc}")
        if bad:
            self.fail("BUILD", "Python syntax", " | ".join(bad))
        else:
            self.success("BUILD", "Python syntax", f"Compiled {len(py_files)} Python files")
        checker = self.root / "tests" / "verify_frontend.mjs"
        if checker.is_file() and shutil.which("node"):
            proc = subprocess.run(["node", str(checker)], cwd=self.root, text=True, capture_output=True)
            if proc.returncode:
                self.fail("BUILD", "JavaScript syntax and handlers", proc.stdout + proc.stderr)
            else:
                self.success("BUILD", "JavaScript syntax and handlers", proc.stdout.strip() or "Node check passed")
        else:
            self.skip("BUILD", "JavaScript syntax and handlers", "Node or tests/verify_frontend.mjs is not available")

    def offline_permissions_and_database(self) -> None:
        with tempfile.TemporaryDirectory(prefix="caesar_preflight_") as td:
            probe = Path(td) / "write_probe.txt"
            try:
                probe.write_text("CAESAR_OFFLINE_PROBE", encoding="utf-8")
                if probe.read_text(encoding="utf-8") != "CAESAR_OFFLINE_PROBE":
                    raise OSError("read-back mismatch")
                self.success("ENVIRONMENT", "Local read/write permissions", td)
            except OSError as exc:
                self.fail("ENVIRONMENT", "Local read/write permissions", str(exc))
            try:
                db = sqlite3.connect(str(Path(td) / "preflight.sqlite3"))
                db.execute("CREATE TABLE health (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("INSERT INTO health(value) VALUES (?)", ("ok",))
                db.commit()
                value = db.execute("SELECT value FROM health WHERE id=1").fetchone()[0]
                db.close()
                if value == "ok":
                    self.success("DATABASE", "Local SQLite create/read/write", "SQLite transaction completed")
                else:
                    self.fail("DATABASE", "Local SQLite create/read/write", "Unexpected row value")
            except Exception as exc:
                self.fail("DATABASE", "Local SQLite create/read/write", repr(exc))

    def core_logic_static(self) -> None:
        source = (self.app / "server.py").read_text(encoding="utf-8", errors="ignore")
        checks = {
            "Product approval and cart pricing": ["def approved_order_items", "subtotal", "'total': total"],
            "Discount calculation and persistence": ["discount_pct", "discount_amount", "manager_approval_required"],
            "Payment normalization": ["def normalize_payment", "cash_amount", "card_amount", "مختلط"],
            "Barcode endpoint": ["@app.route('/api/barcode/<barcode>'", "def get_product_by_barcode"],
            "Order completion endpoint": ["@app.route('/api/orders', methods=['GET', 'POST'])", "data.setdefault('orders', []).append(o)"],
            "Printer test/cut/drawer paths": ["def test_printer", "def cut_paper_to_printer", "def open_cash_drawer_via_printer"],
        }
        for name, needles in checks.items():
            missing = [needle for needle in needles if needle not in source]
            if missing:
                self.fail("CORE", name, "Missing implementation markers: " + ", ".join(missing))
            else:
                self.success("CORE", name, "Implementation markers found")
        tax_markers = re.findall(r"(?:tax_rate|tax_amount|vat_rate|vat_amount|ضريبة|ضريبة مضافة)", source, re.I)
        if self.args.require_tax and not tax_markers:
            self.fail("CORE", "Tax calculation support", "Tax was explicitly required but no tax implementation was found")
        elif tax_markers:
            self.success("CORE", "Tax calculation support", f"Found {len(tax_markers)} tax-related markers")
        else:
            self.skip("CORE", "Tax calculation support", "Not applicable: tax is disabled for this Syrian POS deployment")
        html = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in self.app.glob("*.html"))
        if re.search(r"barcode|باركود", html, re.I) and re.search(r"keydown|keypress|Enter", html, re.I):
            self.success("CORE", "Barcode scanner keyboard input", "Barcode field and Enter-style keyboard handling found")
        else:
            self.fail("CORE", "Barcode scanner keyboard input", "Barcode input or Enter handling is missing")

    def escpos_readiness(self) -> None:
        source = (self.app / "server.py").read_text(encoding="utf-8", errors="ignore")
        markers = ["render_escpos_raster_payload", "Tajawal-Regular.ttf", "0x1d, 0x76, 0x30", "cut_paper_to_printer", "open_cash_drawer_via_printer"]
        missing = [m for m in markers if m not in source]
        if missing:
            self.fail("PRINTER", "Arabic ESC/POS raster readiness", "Missing: " + ", ".join(missing))
            return
        old_home = os.environ.get("HOME")
        with tempfile.TemporaryDirectory(prefix="caesar_raster_") as td:
            os.environ["HOME"] = td
            try:
                sys.path.insert(0, str(self.app))
                import server  # type: ignore
                payload = server.render_escpos_raster_payload("مطعم قيصر فاتورة اختبار 123", 80, "large")
                if payload.startswith(b"\x1b\x40") and b"\x1d\x76\x30" in payload and payload.endswith(b"\x1d\x56\x00"):
                    self.success("PRINTER", "Arabic ESC/POS raster readiness", f"Generated {len(payload)} raster bytes with Tajawal")
                else:
                    self.fail("PRINTER", "Arabic ESC/POS raster readiness", "Raster payload markers are invalid")
            except Exception as exc:
                self.fail("PRINTER", "Arabic ESC/POS raster readiness", repr(exc))
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def tcp_check(self, section: str, name: str, host: str | None, port: int | None, required: bool) -> None:
        if not host or not port:
            (self.fail if required else self.skip)(section, name, "No endpoint configured; provide host and port")
            return
        try:
            with socket.create_connection((host, int(port)), timeout=self.args.timeout):
                self.success(section, name, f"TCP connection succeeded: {host}:{port}")
        except OSError as exc:
            self.fail(section, name, f"TCP connection failed: {host}:{port} ({exc})")

    def hardware(self) -> None:
        required = self.args.strict_hardware
        if self.args.serial_port:
            try:
                import serial  # type: ignore
                handle = serial.Serial(self.args.serial_port, self.args.baudrate, timeout=self.args.timeout)
                handle.close()
                self.success("HARDWARE", "Invoice printer serial/USB port", self.args.serial_port)
            except Exception as exc:
                self.fail("HARDWARE", "Invoice printer serial/USB port", repr(exc))
        else:
            self.tcp_check("HARDWARE", "Invoice printer IP/TCP port", self.args.printer_host, self.args.printer_port, required)
        self.tcp_check("HARDWARE", "Cash drawer local/network port", self.args.cash_drawer_host, self.args.cash_drawer_port, required)
        if self.args.printer_host and self.args.printer_port:
            self.success("HARDWARE", "Offline network endpoint configuration", "Printer endpoint supplied")
        elif required:
            self.fail("HARDWARE", "Offline network endpoint configuration", "Strict hardware mode requires printer endpoint")
        else:
            self.skip("HARDWARE", "Offline network endpoint configuration", "No network printer endpoint supplied")

    def local_http(self) -> None:
        pages = sorted(p.name for p in self.app.glob("*.html"))
        if not pages:
            self.fail("UI", "Page inventory", "No HTML pages found")
            return
        env = os.environ.copy()
        env["HOME"] = tempfile.mkdtemp(prefix="caesar_http_home_")
        env["CAESAR_PORT"] = str(self.args.http_port)
        env["CAESAR_LAN"] = "0"
        proc = subprocess.Popen([sys.executable, str(self.app / "server.py")], cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.time() + self.args.startup_timeout
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", self.args.http_port), timeout=0.5):
                        break
                except OSError:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.2)
            else:
                self.fail("UI", "Local server startup", "Server did not listen before timeout")
                return
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=2)
                self.fail("UI", "Local server startup", f"Exited with {proc.returncode}: {out[-300:]} {err[-300:]}")
                return
            failures = []
            for page in pages:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self.args.http_port}/{page}", timeout=self.args.timeout) as response:
                        if response.status >= 500:
                            failures.append(f"{page}={response.status}")
                except Exception as exc:
                    failures.append(f"{page}: {exc}")
            if failures:
                self.fail("UI", "All local HTML pages respond", " | ".join(failures[:12]))
            else:
                self.success("UI", "All local HTML pages respond", f"Checked {len(pages)} pages without 5xx/crash")
            api_paths = ["/api/version", "/api/menu", "/api/network/info", "/api/printer/settings", "/api/sync/status"]
            failures = []
            for api in api_paths:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self.args.http_port}{api}", timeout=self.args.timeout) as response:
                        if response.status >= 500:
                            failures.append(f"{api}={response.status}")
                except urllib.error.HTTPError as exc:
                    if exc.code >= 500:
                        failures.append(f"{api}={exc.code}")
                except Exception as exc:
                    failures.append(f"{api}: {exc}")
            if failures:
                self.fail("UI", "Core local API endpoints", " | ".join(failures))
            else:
                self.success("UI", "Core local API endpoints", f"Checked {len(api_paths)} endpoints")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def unit_tests(self) -> None:
        tests = self.root / "tests"
        if not tests.is_dir():
            self.skip("CORE", "Automated project unit tests", "tests directory not found")
            return
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"], cwd=self.root, text=True, capture_output=True)
        if proc.returncode:
            self.fail("CORE", "Automated project unit tests", (proc.stdout + proc.stderr)[-1200:])
        else:
            self.success("CORE", "Automated project unit tests", proc.stdout.splitlines()[-1] if proc.stdout else "Passed")

    def write_report(self) -> None:
        report = self.args.report
        if not report:
            return
        payload: dict[str, Any] = {
            "project": str(self.root),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "success": not any(r.status == "FAIL" for r in self.results),
            "results": [asdict(r) for r in self.results],
        }
        Path(report).resolve().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"REPORT: {Path(report).resolve()}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CAESAR POS comprehensive offline pre-flight gate")
    p.add_argument("--root", default=".", help="Project root")
    p.add_argument("--report", default="preflight-report.json", help="JSON report path")
    p.add_argument("--printer-host", default=os.getenv("CAESAR_PRINTER_HOST"))
    p.add_argument("--printer-port", type=int, default=int(os.getenv("CAESAR_PRINTER_PORT", "0") or 0))
    p.add_argument("--serial-port", default=os.getenv("CAESAR_PRINTER_SERIAL"))
    p.add_argument("--cash-drawer-host", default=os.getenv("CAESAR_DRAWER_HOST"))
    p.add_argument("--cash-drawer-port", type=int, default=int(os.getenv("CAESAR_DRAWER_PORT", "0") or 0))
    p.add_argument("--baudrate", type=int, default=int(os.getenv("CAESAR_PRINTER_BAUD", "9600")))
    p.add_argument("--strict-hardware", action="store_true", help="Missing/unreachable hardware is FAIL, not SKIP")
    p.add_argument("--require-tax", action="store_true", help="Require tax implementation; disabled by default")
    p.add_argument("--http-port", type=int, default=18080)
    p.add_argument("--startup-timeout", type=float, default=15)
    p.add_argument("--timeout", type=float, default=3)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(Suite(Path(args.root), args).run())
