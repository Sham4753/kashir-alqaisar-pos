import MaterialIcons from "@expo/vector-icons/MaterialIcons";
import { Tabs } from "expo-router";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export default function TabLayout() {
  const insets = useSafeAreaInsets();
  const bottom = Platform.OS === "web" ? 10 : Math.max(insets.bottom, 8);
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: "#0E9F6E", tabBarInactiveTintColor: "#64748B", tabBarStyle: { backgroundColor: "#FFFFFF", borderTopColor: "#E2E8F0", height: 58 + bottom, paddingTop: 7, paddingBottom: bottom } }}>
      <Tabs.Screen name="index" options={{ title: "الطاولات", tabBarIcon: ({ color }) => <MaterialIcons name="table-restaurant" size={23} color={color} /> }} />
      <Tabs.Screen name="settings" options={{ title: "الحساب", tabBarIcon: ({ color }) => <MaterialIcons name="settings" size={23} color={color} /> }} />
    </Tabs>
  );
}
