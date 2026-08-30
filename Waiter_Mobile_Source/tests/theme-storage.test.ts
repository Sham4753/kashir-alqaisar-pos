import { beforeEach, describe, expect, it, vi } from "vitest";

const values = new Map<string, string>();

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: vi.fn(async (key: string) => values.get(key) ?? null),
    setItem: vi.fn(async (key: string, value: string) => { values.set(key, value); }),
  },
}));
vi.mock("expo-secure-store", () => ({ getItemAsync: vi.fn(), setItemAsync: vi.fn(), deleteItemAsync: vi.fn() }));
vi.mock("react-native", () => ({ Platform: { OS: "web" } }));

import { loadThemePreference, saveThemePreference } from "../lib/kashir-storage";

describe("waiter theme preference", () => {
  beforeEach(() => values.clear());

  it("persists the dark preference and restores it", async () => {
    await saveThemePreference("dark");
    await expect(loadThemePreference()).resolves.toBe("dark");
  });

  it("ignores unexpected stored values", async () => {
    values.set("kashir_waiter_theme_v1", "system");
    await expect(loadThemePreference()).resolves.toBeNull();
  });
});
