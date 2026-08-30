import { Stack } from "expo-router";

import { WaiterProvider } from "@/lib/waiter-context";
import { ThemeProvider } from "@/lib/theme-provider";

export default function RootLayout() {
  return (
    <ThemeProvider>
      <WaiterProvider>
        <Stack screenOptions={{ headerShown: false, animation: "fade" }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="order" options={{ presentation: "card" }} />
        </Stack>
      </WaiterProvider>
    </ThemeProvider>
  );
}
