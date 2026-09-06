#!/usr/bin/env python3
"""Generate an offline CAESAR POS HMAC-SHA256 license."""
import hashlib, hmac, os
SECRET = os.environ.get("CAESAR_LICENSE_SECRET", "caesar-pos-commercial-license-v4-2026").encode("utf-8")
def normalize(machine_id):
    return "".join(c for c in str(machine_id).strip().upper() if c.isalnum() or c in ":_-")
def generate(machine_id):
    machine_id = normalize(machine_id)
    number = "CAESAR-" + hashlib.sha256(machine_id.encode()).hexdigest()[:12].upper()
    digest = hmac.new(SECRET, f"{machine_id}|{number}".encode(), hashlib.sha256).hexdigest().upper()
    return number, "-".join(digest[i:i+8] for i in range(0, 32, 8))
def main():
    machine_id = input("Machine ID: ").strip()
    if not machine_id: raise SystemExit("Machine ID is required.")
    number, key = generate(machine_id)
    print(f"\nProduct: CAESAR POS\nLicense ID: {number}\nLicense Key: {key}")
    input("\nاضغط Enter للخروج...")
if __name__ == "__main__": main()
