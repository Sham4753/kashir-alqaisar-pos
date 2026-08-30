import MaterialIcons from "@expo/vector-icons/MaterialIcons";
import { CameraView, type BarcodeScanningResult, useCameraPermissions } from "expo-camera";
import { useEffect, useState } from "react";
import { ActivityIndicator, Alert, Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";

import { useColors } from "@/hooks/use-colors";
import { decodeWaiterConnectionQr } from "@/lib/waiter-connection-qr";

export function WaiterConnectionScanner({ visible, onClose, onScanned }: { visible: boolean; onClose: () => void; onScanned: (baseUrl: string) => void }) {
  const colors = useColors();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  useEffect(() => { if (visible) setScanned(false); }, [visible]);
  if (!visible) return null;
  const handleScan = ({ data }: BarcodeScanningResult) => {
    const baseUrl = decodeWaiterConnectionQr(data);
    if (!baseUrl) {
      setScanned(true);
      Alert.alert("رمز غير صالح", "امسح رمز ربط تطبيق النادل الظاهر في إعدادات الشبكة داخل الكاشير.", [{ text: "إعادة المسح", onPress: () => setScanned(false) }]);
      return;
    }
    setScanned(true);
    onScanned(baseUrl);
  };

  return <Modal visible animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}><View style={[styles.root, { backgroundColor: colors.background }]}><View style={styles.header}><View style={styles.headerText}><Text style={[styles.title, { color: colors.foreground }]}>مسح رمز ربط النادل</Text><Text style={[styles.subtitle, { color: colors.muted }]}>وجّه الكاميرا إلى الرمز الأخضر في إعدادات شبكة الكاشير.</Text></View><Pressable onPress={onClose} accessibilityLabel="إغلاق الماسح" style={({ pressed }) => [styles.close, { backgroundColor: colors.surface, borderColor: colors.border }, pressed && styles.pressed]}><MaterialIcons name="close" size={23} color={colors.foreground} /></Pressable></View>{!permission ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : !permission.granted ? <View style={styles.center}><MaterialIcons name="photo-camera" size={42} color={colors.primary} /><Text style={[styles.permissionTitle, { color: colors.foreground }]}>يلزم إذن الكاميرا</Text><Text style={[styles.permissionText, { color: colors.muted }]}>يُستخدم لمسح رمز عنوان الكاشير المحلي فقط.</Text><Pressable onPress={requestPermission} style={({ pressed }) => [styles.permissionButton, { backgroundColor: colors.primary }, pressed && styles.pressed]}><Text style={styles.permissionButtonText}>السماح بالكاميرا</Text></Pressable>{Platform.OS === "web" ? <Text style={[styles.webHint, { color: colors.muted }]}>قد يتطلب متصفح الويب إذن كاميرا صريحًا.</Text> : null}</View> : <View style={styles.cameraWrap}><CameraView style={styles.camera} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }} onBarcodeScanned={scanned ? undefined : handleScan} /><View pointerEvents="none" style={[styles.frame, { borderColor: colors.primary }]} /><Text style={styles.cameraHint}>{scanned ? "تمت قراءة الرمز…" : "ضع رمز الربط داخل الإطار"}</Text></View>}</View></Modal>;
}

const styles = StyleSheet.create({ root: { flex: 1, paddingTop: 56 }, header: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", paddingHorizontal: 20, paddingBottom: 18 }, headerText: { flex: 1, paddingEnd: 16 }, title: { fontSize: 22, fontWeight: "800" }, subtitle: { fontSize: 13, lineHeight: 20, marginTop: 5 }, close: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 15 }, center: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: 32 }, permissionTitle: { fontSize: 19, fontWeight: "800", marginTop: 14 }, permissionText: { fontSize: 13, lineHeight: 20, textAlign: "center", marginTop: 7 }, permissionButton: { marginTop: 22, minHeight: 50, paddingHorizontal: 24, borderRadius: 14, alignItems: "center", justifyContent: "center" }, permissionButtonText: { color: "#FFFFFF", fontSize: 15, fontWeight: "800" }, webHint: { marginTop: 14, fontSize: 11, textAlign: "center" }, cameraWrap: { flex: 1, margin: 20, borderRadius: 24, overflow: "hidden", backgroundColor: "#0F172A", position: "relative" }, camera: { flex: 1 }, frame: { position: "absolute", width: 230, height: 230, borderWidth: 3, borderRadius: 24, top: "30%", alignSelf: "center" }, cameraHint: { position: "absolute", bottom: 34, alignSelf: "center", color: "#FFFFFF", backgroundColor: "#0F172ACC", paddingHorizontal: 16, paddingVertical: 10, borderRadius: 20, fontSize: 13, fontWeight: "700" }, pressed: { opacity: 0.86, transform: [{ scale: 0.98 }] } });
