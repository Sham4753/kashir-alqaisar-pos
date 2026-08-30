import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Animated, Appearance, Easing, StyleSheet, View, useColorScheme as useSystemColorScheme } from "react-native";
import { colorScheme as nativewindColorScheme, vars } from "nativewind";

import { SchemeColors, type ColorScheme } from "@/constants/theme";
import { loadThemePreference, saveThemePreference } from "@/lib/kashir-storage";

type ThemeContextValue = {
  colorScheme: ColorScheme;
  setColorScheme: (scheme: ColorScheme) => void;
  isThemeTransitioning: boolean;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const systemScheme = useSystemColorScheme() ?? "light";
  const [colorScheme, setColorSchemeState] = useState<ColorScheme>(systemScheme);
  const [isThemeTransitioning, setIsThemeTransitioning] = useState(false);
  const transitionOpacity = useRef(new Animated.Value(0)).current;
  const transitionColor = useRef(SchemeColors[systemScheme].background);

  const applyScheme = useCallback((scheme: ColorScheme) => {
    nativewindColorScheme.set(scheme);
    Appearance.setColorScheme?.(scheme);
    if (typeof document !== "undefined") {
      const root = document.documentElement;
      root.dataset.theme = scheme;
      root.classList.toggle("dark", scheme === "dark");
      const palette = SchemeColors[scheme];
      Object.entries(palette).forEach(([token, value]) => {
        root.style.setProperty(`--color-${token}`, value);
      });
    }
  }, []);

  const setColorScheme = useCallback((scheme: ColorScheme) => {
    if (scheme === colorScheme || isThemeTransitioning) return;
    transitionColor.current = SchemeColors[colorScheme].background;
    setIsThemeTransitioning(true);
    Animated.timing(transitionOpacity, { toValue: 1, duration: 110, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start(({ finished }) => {
      if (!finished) { setIsThemeTransitioning(false); return; }
    setColorSchemeState(scheme);
    applyScheme(scheme);
    saveThemePreference(scheme).catch(() => undefined);
      Animated.timing(transitionOpacity, { toValue: 0, duration: 180, easing: Easing.inOut(Easing.cubic), useNativeDriver: true }).start(() => setIsThemeTransitioning(false));
    });
  }, [applyScheme, colorScheme, isThemeTransitioning, transitionOpacity]);

  useEffect(() => {
    applyScheme(colorScheme);
  }, [applyScheme, colorScheme]);

  useEffect(() => {
    let mounted = true;
    loadThemePreference()
      .then((saved) => {
        if (mounted && saved) setColorSchemeState(saved);
      })
      .catch(() => undefined);
    return () => { mounted = false; };
  }, []);

  const themeVariables = useMemo(
    () =>
      vars({
        "color-primary": SchemeColors[colorScheme].primary,
        "color-background": SchemeColors[colorScheme].background,
        "color-surface": SchemeColors[colorScheme].surface,
        "color-foreground": SchemeColors[colorScheme].foreground,
        "color-muted": SchemeColors[colorScheme].muted,
        "color-border": SchemeColors[colorScheme].border,
        "color-success": SchemeColors[colorScheme].success,
        "color-warning": SchemeColors[colorScheme].warning,
        "color-error": SchemeColors[colorScheme].error,
      }),
    [colorScheme],
  );

  const value = useMemo(
    () => ({
      colorScheme,
      setColorScheme,
      isThemeTransitioning,
    }),
    [colorScheme, isThemeTransitioning, setColorScheme],
  );
  return (
    <ThemeContext.Provider value={value}>
      <View style={[styles.root, themeVariables]}>
        {children}
        <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { backgroundColor: transitionColor.current, opacity: transitionOpacity }]} />
      </View>
    </ThemeContext.Provider>
  );
}

export function useThemeContext(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useThemeContext must be used within ThemeProvider");
  }
  return ctx;
}

const styles = StyleSheet.create({ root: { flex: 1, overflow: "hidden" } });
