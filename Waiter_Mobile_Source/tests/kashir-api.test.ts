import { beforeEach, describe, expect, it, vi } from "vitest";

import { normalizeBaseUrl, waiterApi } from "../lib/kashir-api";
import type { Connection } from "../lib/kashir-types";

const connection: Connection = {
  baseUrl: "http://192.168.1.20:8080",
  token: "test-waiter-token",
  expiresAt: "2030-01-01T00:00:00.000Z",
  user: { id: 1, username: "waiter_test", role: "waiter" },
};

describe("Kashir waiter local API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes a bare local address without changing an existing protocol", () => {
    expect(normalizeBaseUrl("192.168.1.20:8080/")).toBe("http://192.168.1.20:8080");
    expect(normalizeBaseUrl("https://cashier.local:8080/")).toBe("https://cashier.local:8080");
    expect(normalizeBaseUrl("   ")).toBe("");
  });

  it("sends the protected waiter token to the tables endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, tables: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(waiterApi.tables(connection)).resolves.toEqual({ ok: true, tables: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://192.168.1.20:8080/api/mobile/tables",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer test-waiter-token" }) }),
    );
  });

  it("uses a POST request when confirming service", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, session: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await waiterApi.markServed(connection, "DINE-123");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://192.168.1.20:8080/api/mobile/dine-in/sessions/DINE-123/served",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
