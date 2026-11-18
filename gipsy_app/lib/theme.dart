import 'package:flutter/material.dart';

/// Navy + amber, matching John's logo set.
class GipsyColors {
  static const navyDeep = Color(0xFF0A0F1C); // app background
  static const navy = Color(0xFF121A2E); // cards
  static const navyPlate = Color(0xFF26324D); // helmet armour
  static const navyGlow = Color(0xFF4A6FA5);
  static const steel = Color(0xFF8A97B3);
  static const amber = Color(0xFFFF9A1F);
  static const amberHot = Color(0xFFFFC14D);
  static const amberDeep = Color(0xFFD9620B);
}

ThemeData gipsyTheme() {
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: ColorScheme.fromSeed(
      seedColor: GipsyColors.amber,
      brightness: Brightness.dark,
      primary: GipsyColors.amber,
      surface: GipsyColors.navy,
    ),
    scaffoldBackgroundColor: GipsyColors.navyDeep,
  );
  return base.copyWith(
    appBarTheme: const AppBarTheme(backgroundColor: GipsyColors.navyDeep, elevation: 0, centerTitle: true),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: GipsyColors.navy,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
    ),
  );
}
