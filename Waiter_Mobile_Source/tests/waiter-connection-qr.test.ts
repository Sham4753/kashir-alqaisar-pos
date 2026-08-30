import { describe, expect, it } from "vitest";

import { decodeWaiterConnectionQr, WAITER_CONNECTION_QR_PREFIX } from "../lib/waiter-connection-qr";

describe("waiter connection QR", () => {
  it("extracts the local cashier base URL from the dedicated QR payload", () => {
    expect(decodeWaiterConnectionQr(`${WAITER_CONNECTION_QR_PREFIX}http://192.168.1.20:8080`)).toBe("http://192.168.1.20:8080");
    expect(decodeWaiterConnectionQr("http://cashier.local:8080")).toBe("http://cashier.local:8080");
  });

  it("rejects links that could carry routes, credentials, or an unsupported scheme", () => {
    expect(decodeWaiterConnectionQr(`${WAITER_CONNECTION_QR_PREFIX}http://user:pass@192.168.1.20:8080`)).toBeNull();
    expect(decodeWaiterConnectionQr(`${WAITER_CONNECTION_QR_PREFIX}https://192.168.1.20:8080/mobile.html`)).toBeNull();
    expect(decodeWaiterConnectionQr("ftp://192.168.1.20:8080")).toBeNull();
  });
});
