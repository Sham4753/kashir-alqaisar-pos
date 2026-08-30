export const WAITER_CONNECTION_QR_PREFIX = "QAISAR_WAITER_V1|";

/** يحول رمز الربط إلى عنوان خادم محلي فقط؛ لا يقبل مسارًا أو بيانات اعتماد أو رابطًا غير HTTP(S). */
export function decodeWaiterConnectionQr(value: string): string | null {
  const raw = String(value ?? "").trim();
  const candidate = raw.startsWith(WAITER_CONNECTION_QR_PREFIX) ? raw.slice(WAITER_CONNECTION_QR_PREFIX.length) : raw;
  if (!candidate) return null;
  try {
    const normalized = /^https?:\/\//i.test(candidate) ? candidate : `http://${candidate}`;
    const url = new URL(normalized);
    if (!/^https?:$/.test(url.protocol) || !url.hostname || url.username || url.password || url.pathname !== "/" || url.search || url.hash) return null;
    return url.origin;
  } catch {
    return null;
  }
}
