import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import type { Connection } from "@/lib/kashir-types";

const KEY = "kashir_waiter_connection_v1";
const THEME_KEY = "kashir_waiter_theme_v1";

async function nativeSet(value: string) {
  if (Platform.OS === "web") {
    globalThis.localStorage?.setItem(KEY, value);
    return;
  }
  await SecureStore.setItemAsync(KEY, value);
}

async function nativeGet() {
  if (Platform.OS === "web") return globalThis.localStorage?.getItem(KEY) ?? null;
  return SecureStore.getItemAsync(KEY);
}

export async function loadConnection(): Promise<Connection | null> {
  try {
    const raw = await nativeGet();
    if (!raw) return null;
    const saved = JSON.parse(raw) as Connection;
    if (!saved.token || !saved.baseUrl || new Date(saved.expiresAt).getTime() <= Date.now()) {
      await clearConnection();
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

export async function saveConnection(value: Connection) {
  await nativeSet(JSON.stringify(value));
  await AsyncStorage.setItem("kashir_waiter_last_host", value.baseUrl);
}

export async function clearConnection() {
  if (Platform.OS === "web") globalThis.localStorage?.removeItem(KEY);
  else await SecureStore.deleteItemAsync(KEY);
}

export async function loadLastHost() {
  return (await AsyncStorage.getItem("kashir_waiter_last_host")) ?? "";
}

export async function loadThemePreference(): Promise<"light" | "dark" | null> {
  const value = await AsyncStorage.getItem(THEME_KEY);
  return value === "light" || value === "dark" ? value : null;
}

export async function saveThemePreference(value: "light" | "dark") {
  await AsyncStorage.setItem(THEME_KEY, value);
}
