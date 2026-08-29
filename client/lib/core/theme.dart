import 'package:flutter/material.dart';

/// Minimalist dark mode design system palette and theme configuration.
class AppTheme {
  // Color Palette
  static const Color backgroundDarkest = Color(0xFF0F1012);
  static const Color backgroundSidebar = Color(0xFF18191C);
  static const Color backgroundMain = Color(0xFF1E1F22);
  static const Color backgroundSurface = Color(0xFF2B2D31);
  static const Color backgroundElevated = Color(0xFF35373C);

  // Accent & Action Colors
  static const Color primary = Color(0xFF5865F2);
  static const Color primaryHover = Color(0xFF4752C4);
  static const Color speakingGreen = Color(0xFF23A55A);
  static const Color warningYellow = Color(0xFFF0B232);
  static const Color dangerRed = Color(0xFFF23F43);
  static const Color statusOnline = Color(0xFF23A55A);
  static const Color statusIdle = Color(0xFFF0B232);
  static const Color statusDnd = Color(0xFFF23F43);
  static const Color statusOffline = Color(0xFF80848E);

  // Typography Colors
  static const Color textPrimary = Color(0xFFFFFFFF);
  static const Color textSecondary = Color(0xFFDBDEE1);
  static const Color textMuted = Color(0xFF949BA4);
  static const Color dividerColor = Color(0xFF202225);

  /// Builds the high-contrast dark desktop theme.
  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: backgroundMain,
      colorScheme: const ColorScheme.dark(
        primary: primary,
        surface: backgroundSurface,
        error: dangerRed,
        onPrimary: Colors.white,
        onSurface: textPrimary,
        onError: Colors.white,
      ),
      fontFamily: 'Segoe UI',
      dividerTheme: const DividerThemeData(
        color: dividerColor,
        thickness: 1,
        space: 1,
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStateProperty.all(const Color(0xFF1A1B1E)),
        trackColor: WidgetStateProperty.all(Colors.transparent),
        radius: const Radius.circular(4),
        thickness: WidgetStateProperty.all(6),
      ),
      dialogTheme: const DialogThemeData(
        backgroundColor: backgroundElevated,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(8)),
        ),
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF383A40),
        hintStyle: const TextStyle(color: textMuted, fontSize: 14),
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: const BorderSide(color: primary, width: 1.5),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(4),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w500,
            fontSize: 14,
          ),
        ),
      ),
      sliderTheme: const SliderThemeData(
        activeTrackColor: primary,
        inactiveTrackColor: Color(0xFF4E5058),
        thumbColor: Colors.white,
        overlayColor: Color(0x335865F2),
        trackHeight: 4,
      ),
      tooltipTheme: const TooltipThemeData(
        decoration: BoxDecoration(
          color: backgroundDarkest,
          borderRadius: BorderRadius.all(Radius.circular(4)),
        ),
        textStyle: TextStyle(color: textPrimary, fontSize: 12),
        waitDuration: Duration(milliseconds: 400),
      ),
    );
  }
}
