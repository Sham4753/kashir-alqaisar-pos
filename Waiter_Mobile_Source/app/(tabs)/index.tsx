import MaterialIcons from "@expo/vector-icons/MaterialIcons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, Alert, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from "react-native";

import { ScreenContainer } from "@/components/screen-container";
import { useColors } from "@/hooks/use-colors";
import { waiterApi } from "@/lib/kashir-api";
import type { RestaurantTable } from "@/lib/kashir-types";
import { useWaiter } from "@/lib/waiter-context";

type Filter = "all" | "free" | "busy" | "ready";

export default function TablesScreen() {
  const router = useRouter();
  const colors = useColors();
  const { connection, ready } = useWaiter();
  const [tables, setTables] = useState<RestaurantTable[]>([]);
  const [restaurantName, setRestaurantName] = useState("كاشير القيصر");
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const loadTables = useCallback(async () => {
    if (!connection) return;
    setLoading(true); setError("");
    try {
      const [tableData, bootstrap] = await Promise.all([waiterApi.tables(connection), waiterApi.bootstrap(connection)]);
      setTables(tableData.tables); setRestaurantName(bootstrap.restaurant.name || "كاشير القيصر");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "تعذر تحديث الطاولات"); }
    finally { setLoading(false); }
  }, [connection]);
  useFocusEffect(useCallback(() => { loadTables(); }, [loadTables]));
  const visibleTables = useMemo(() => tables.filter((table) => filter === "all" || (filter === "ready" ? table.active_session?.kitchen_status === "ready" : table.status === filter)), [tables, filter]);
  const counters = useMemo(() => ({ all: tables.length, free: tables.filter((table) => table.status === "free").length, busy: tables.filter((table) => table.status === "busy").length, ready: tables.filter((table) => table.active_session?.kitchen_status === "ready").length }), [tables]);
  const openTable = (table: RestaurantTable) => {
    if (table.status === "reserved") return Alert.alert("طاولة محجوزة", "لا يمكن للنادل فتح طلب جديد على هذه الطاولة.");
    router.push({ pathname: "/order" as never, params: { tableId: table.id, sessionId: table.active_session?.id ?? "" } } as never);
  };
  if (!ready) return <ScreenContainer className="items-center justify-center"><ActivityIndicator color={colors.primary} /></ScreenContainer>;
  if (!connection) return <ConnectCard colors={colors} onConnect={() => router.push("/settings" as never)} />;
  return <ScreenContainer containerClassName="bg-background" className="px-4"><View style={styles.header}><View style={{ flex: 1 }}><Text style={[styles.eyebrow, { color: colors.primary }]}>شبكة المطعم المحلية</Text><Text style={[styles.title, { color: colors.foreground }]}>{restaurantName}</Text><Text style={[styles.subtitle, { color: colors.muted }]}>أهلًا {connection.user.username} · حدّث الطاولات أثناء الخدمة</Text></View><Pressable accessibilityLabel="تحديث الطاولات" onPress={loadTables} style={({ pressed }) => [styles.iconButton, { backgroundColor: colors.surface, borderColor: colors.border }, pressed && styles.pressed]}><MaterialIcons name="refresh" size={23} color={colors.foreground} /></Pressable></View><View style={styles.filters}>{(["all", "free", "busy", "ready"] as Filter[]).map((item) => <Pressable key={item} onPress={() => setFilter(item)} style={[styles.filter, { backgroundColor: filter === item ? colors.foreground : colors.surface, borderColor: filter === item ? colors.foreground : colors.border }]}><Text style={[styles.filterText, { color: filter === item ? colors.background : colors.muted }]}>{({ all: "الكل", free: "شاغرة", busy: "مشغولة", ready: "جاهز" })[item]} · {counters[item]}</Text></Pressable>)}</View>{error ? <Pressable onPress={loadTables} style={[styles.errorBox, { backgroundColor: colors.error + "22", borderColor: colors.error + "66" }]}><Text style={[styles.errorText, { color: colors.error }]}>{error} — اضغط للمحاولة مجددًا</Text></Pressable> : null}<FlatList data={visibleTables} keyExtractor={(table) => table.id} numColumns={2} columnWrapperStyle={visibleTables.length > 1 ? styles.gridRow : undefined} contentContainerStyle={styles.grid} refreshControl={<RefreshControl refreshing={loading} onRefresh={loadTables} tintColor={colors.primary} />} ListEmptyComponent={<EmptyState loading={loading} colors={colors} />} renderItem={({ item }) => <TableCard table={item} colors={colors} onPress={() => openTable(item)} />} /></ScreenContainer>;
}

function TableCard({ table, colors, onPress }: { table: RestaurantTable; colors: ReturnType<typeof useColors>; onPress: () => void }) {
  const meta = table.status === "free" ? { label: "شاغرة", color: colors.success } : table.status === "reserved" ? { label: "محجوزة", color: "#A78BFA" } : { label: "مشغولة", color: colors.warning };
  const kitchen = table.active_session?.kitchen_status;
  const kitchenLabel = kitchen === "ready" ? "جاهز للتقديم" : kitchen === "preparing" ? "قيد التحضير" : kitchen === "served" ? "تم التقديم" : kitchen === "new" ? "طلب جديد" : "قيد الخدمة";
  const isReady = kitchen === "ready";
  return <Pressable onPress={onPress} style={({ pressed }) => [styles.tableCard, { backgroundColor: colors.surface, borderColor: isReady ? colors.primary : colors.border }, pressed && styles.pressed]}><View style={styles.tableTop}><View style={[styles.statusDot, { backgroundColor: meta.color }]} /><Text style={[styles.statusLabel, { color: meta.color }]}>{meta.label}</Text></View><View style={[styles.tableIcon, { backgroundColor: colors.background }]}><MaterialIcons name="table-restaurant" size={26} color={colors.foreground} /></View><Text style={[styles.tableName, { color: colors.foreground }]}>{table.name}</Text><Text style={[styles.tableMeta, { color: colors.muted }]}>{table.zone} · {table.seats} مقاعد</Text>{table.active_session ? <View style={[styles.kitchenBadge, { backgroundColor: isReady ? colors.success + "22" : colors.warning + "22" }]}><MaterialIcons name={isReady ? "room-service" : "restaurant"} color={isReady ? colors.success : colors.warning} size={16} /><Text style={[styles.kitchenText, { color: isReady ? colors.success : colors.warning }]}>{kitchenLabel} · {table.active_session.total.toLocaleString("ar")}</Text></View> : <View style={styles.startBadge}><MaterialIcons name="add" color={colors.primary} size={17} /><Text style={[styles.startText, { color: colors.primary }]}>فتح طلب صالة</Text></View>}</Pressable>;
}

function ConnectCard({ colors, onConnect }: { colors: ReturnType<typeof useColors>; onConnect: () => void }) { return <ScreenContainer containerClassName="bg-background" className="p-5 justify-center"><View style={[styles.connectCard, { backgroundColor: colors.surface, borderColor: colors.border }]}><View style={[styles.connectIcon, { backgroundColor: colors.primary + "22" }]}><MaterialIcons name="wifi-tethering" size={34} color={colors.primary} /></View><Text style={[styles.connectTitle, { color: colors.foreground }]}>اربط تطبيق النادل بالكاشير</Text><Text style={[styles.connectText, { color: colors.muted }]}>تأكد أن الهاتف والكمبيوتر على شبكة Wi‑Fi نفسها، ثم أضف عنوان الكاشير وحساب النادل.</Text><Pressable onPress={onConnect} style={({ pressed }) => [styles.primaryButton, { backgroundColor: colors.primary }, pressed && styles.pressed]}><Text style={styles.primaryButtonText}>بدء الربط</Text><MaterialIcons name="arrow-back" size={20} color="#FFFFFF" /></Pressable></View></ScreenContainer>; }
function EmptyState({ loading, colors }: { loading: boolean; colors: ReturnType<typeof useColors> }) { return <View style={styles.empty}><ActivityIndicator animating={loading} color={colors.primary} size="small" /><MaterialIcons name={loading ? "sync" : "table-bar"} size={34} color={colors.muted} /><Text style={[styles.emptyText, { color: colors.muted }]}>{loading ? "جارِ تحديث الصالة…" : "لا توجد طاولات ضمن هذا الفلتر"}</Text></View>; }

const styles = StyleSheet.create({ header: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingTop: 12, paddingBottom: 14 }, eyebrow: { fontSize: 12, fontWeight: "700" }, title: { fontSize: 25, fontWeight: "800", marginTop: 3 }, subtitle: { fontSize: 12, marginTop: 4 }, iconButton: { width: 44, height: 44, borderWidth: 1, borderRadius: 15, alignItems: "center", justifyContent: "center" }, filters: { flexDirection: "row", gap: 7, marginBottom: 16 }, filter: { flex: 1, borderWidth: 1, borderRadius: 12, paddingVertical: 9, alignItems: "center" }, filterText: { fontSize: 11, fontWeight: "700" }, grid: { paddingBottom: 20, gap: 11 }, gridRow: { gap: 11 }, tableCard: { flex: 1, minHeight: 188, borderWidth: 1, borderRadius: 20, padding: 14, shadowColor: "#000000", shadowOpacity: 0.12, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 2 }, tableTop: { flexDirection: "row", alignItems: "center", gap: 5 }, statusDot: { width: 7, height: 7, borderRadius: 4 }, statusLabel: { fontSize: 11, fontWeight: "800" }, tableIcon: { alignSelf: "flex-start", borderRadius: 12, padding: 8, marginTop: 14 }, tableName: { fontSize: 16, fontWeight: "800", marginTop: 10 }, tableMeta: { fontSize: 11, marginTop: 3 }, kitchenBadge: { marginTop: "auto", flexDirection: "row", alignItems: "center", gap: 4, borderRadius: 10, paddingHorizontal: 7, paddingVertical: 6 }, kitchenText: { fontSize: 10, fontWeight: "700", flexShrink: 1 }, startBadge: { marginTop: "auto", flexDirection: "row", alignItems: "center", gap: 3 }, startText: { fontSize: 11, fontWeight: "800" }, errorBox: { borderWidth: 1, padding: 10, borderRadius: 12, marginBottom: 12 }, errorText: { fontSize: 12, textAlign: "center" }, empty: { alignItems: "center", paddingTop: 80, gap: 10 }, emptyText: { fontSize: 14 }, connectCard: { borderRadius: 24, padding: 25, alignItems: "center", borderWidth: 1 }, connectIcon: { width: 72, height: 72, borderRadius: 22, alignItems: "center", justifyContent: "center", marginBottom: 18 }, connectTitle: { fontSize: 21, fontWeight: "800", textAlign: "center" }, connectText: { fontSize: 14, lineHeight: 22, textAlign: "center", marginTop: 9, marginBottom: 23 }, primaryButton: { alignSelf: "stretch", minHeight: 52, borderRadius: 15, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8 }, primaryButtonText: { color: "#FFFFFF", fontSize: 16, fontWeight: "800" }, pressed: { transform: [{ scale: 0.98 }], opacity: 0.9 } });
