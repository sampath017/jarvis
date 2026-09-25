import 'package:flutter/material.dart';

/// A calm Material dark palette with color reserved for state and action.
class AppTheme {
  static const Color background = Color(0xFF111318);
  static const Color surface = Color(0xFF1D2026);
  static const Color surfaceBright = Color(0xFF292D35);
  static const Color border = Color(0xFF393E47);

  static const Color primary = Color(0xFF397CE5);
  static const Color cyan = primary;
  static const Color accent = Color(0xFFC5A2F3);
  static const Color amber = Color(0xFFF9C46B);
  static const Color green = Color(0xFF81C995);
  static const Color red = Color(0xFFF28B82);
  static const Color textPrimary = Color(0xFFE8EAED);
  static const Color textSecondary = Color(0xFFA9AFB8);

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      primaryColor: primary,
      colorScheme: const ColorScheme.dark(
        primary: primary,
        onPrimary: Colors.white,
        secondary: accent,
        onSecondary: background,
        surface: surface,
        error: red,
        onError: background,
      ),
      dividerColor: border,
      splashColor: primary.withValues(alpha: 0.10),
      highlightColor: Colors.transparent,
      appBarTheme: const AppBarTheme(
        backgroundColor: surface,
        foregroundColor: textPrimary,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 20,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
        ),
      ),
      cardTheme: CardThemeData(
        color: surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          side: const BorderSide(color: border),
          borderRadius: BorderRadius.circular(16),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primary,
          foregroundColor: Colors.white,
          elevation: 0,
          minimumSize: const Size(0, 44),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(22),
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surfaceBright,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
        hintStyle: const TextStyle(color: textSecondary),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: primary, width: 2),
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: primary,
        foregroundColor: Colors.white,
        elevation: 1,
        shape: StadiumBorder(),
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: Color(0xFF303134),
        contentTextStyle: TextStyle(color: Colors.white),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }
}
