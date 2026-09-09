import 'package:flutter/material.dart';

/// Futuristic dark telemetry HUD theme for Jarvis.
class AppTheme {
  static const Color background = Color(0xFF090D16);
  static const Color surface = Color(0xFF131A26);
  static const Color surfaceBright = Color(0xFF1C2636);
  static const Color border = Color(0xFF26354A);

  static const Color cyan = Color(0xFF00E5FF);
  static const Color amber = Color(0xFFFF9100);
  static const Color primary = Color(0xFF00E5FF);
  static const Color accent = Color(0xFFFF9100);
  static const Color green = Color(0xFF00E676);
  static const Color red = Color(0xFFFF1744);
  static const Color textPrimary = Color(0xFFE6EDF3);
  static const Color textSecondary = Color(0xFF8B949E);

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      primaryColor: cyan,
      colorScheme: const ColorScheme.dark(
        primary: cyan,
        secondary: amber,
        surface: surface,
        error: red,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: background,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 20,
          fontWeight: FontWeight.bold,
          letterSpacing: 1.2,
        ),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 2,
        shape: RoundedRectangleBorder(
          side: const BorderSide(color: border, width: 1),
          borderRadius: BorderRadius.circular(14),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          elevation: 4,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.bold,
            letterSpacing: 1.0,
          ),
        ),
      ),
    );
  }
}
