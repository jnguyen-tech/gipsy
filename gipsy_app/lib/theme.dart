import 'package:flutter/material.dart';

/// Colours sampled from John's logo set and concept art:
/// dark charcoal-navy background, slate-blue armour plates with lit steel
/// edges, and an amber/orange reactor glow.
class GipsyColors {
  static const navyDeep = Color(0xFF0A0E16); // app background
  static const navy = Color(0xFF111724); // panels
  static const navyRaised = Color(0xFF171E2E); // raised panels
  static const navyPlate = Color(0xFF3E455D); // kept for older code
  static const navyGlow = Color(0xFF4A6FA5); // standby glow when asleep

  static const armorLight = Color(0xFF505975);
  static const armor = Color(0xFF414860);
  static const armorShadow = Color(0xFF262B3B);
  static const armorEdge = Color(0xFF616987);

  static const steel = Color(0xFF8E97B0); // secondary text
  static const steelBright = Color(0xFFC9CFDD); // headings

  static const amber = Color(0xFFFA992C);
  static const amberHot = Color(0xFFFCCD4F); // reactor centre
  static const amberDeep = Color(0xFFDC6E08);
  static const stripe = Color(0xFFEF8725); // accent lines, like the G logo
}

ThemeData gipsyTheme() {
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: ColorScheme.fromSeed(
      seedColor: GipsyColors.amber,
      brightness: Brightness.dark,
      primary: GipsyColors.amber,
      onPrimary: const Color(0xFF1A0E00),
      secondary: GipsyColors.armorEdge,
      surface: GipsyColors.navy,
    ),
    scaffoldBackgroundColor: GipsyColors.navyDeep,
  );
  return base.copyWith(
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: true,
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Colors.transparent,
      border: InputBorder.none,
      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? GipsyColors.amberHot : GipsyColors.steel,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? GipsyColors.amberDeep : GipsyColors.armorShadow,
      ),
    ),
    popupMenuTheme: const PopupMenuThemeData(color: GipsyColors.navyRaised),
  );
}

/// Background with a soft spotlight, like the concept art's dark studio.
class GipsyBackground extends StatelessWidget {
  const GipsyBackground({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(
      gradient: RadialGradient(
        center: Alignment(0, -0.6),
        radius: 1.3,
        colors: [Color(0xFF1A2132), GipsyColors.navyDeep, Color(0xFF06080D)],
        stops: [0, 0.6, 1],
      ),
    ),
    child: child,
  );
}

/// An armour panel: cut corners, a thin steel border and an optional
/// amber accent line, like the panels on John's concept sheet.
class ChamferPanel extends StatelessWidget {
  const ChamferPanel({
    super.key,
    required this.child,
    this.cut = 12,
    this.fill = GipsyColors.navy,
    this.border = GipsyColors.armorEdge,
    this.accent = false,
    this.padding = const EdgeInsets.all(12),
    this.cutTopLeft = true,
    this.cutBottomRight = true,
  });
  final Widget child;
  final double cut;
  final Color fill;
  final Color border;
  final bool accent;
  final EdgeInsets padding;
  final bool cutTopLeft;
  final bool cutBottomRight;

  @override
  Widget build(BuildContext context) => CustomPaint(
    painter: _ChamferPainter(cut, fill, border, accent, cutTopLeft, cutBottomRight),
    child: Padding(padding: padding, child: child),
  );
}

class _ChamferPainter extends CustomPainter {
  _ChamferPainter(this.cut, this.fill, this.border, this.accent, this.tl, this.br);
  final double cut;
  final Color fill, border;
  final bool accent, tl, br;

  @override
  void paint(Canvas canvas, Size s) {
    final c = cut.clamp(0, s.shortestSide / 2).toDouble();
    final p = Path()
      ..moveTo(tl ? c : 0, 0)
      ..lineTo(s.width, 0)
      ..lineTo(s.width, br ? s.height - c : s.height)
      ..lineTo(br ? s.width - c : s.width, s.height)
      ..lineTo(0, s.height)
      ..lineTo(0, tl ? c : 0)
      ..close();
    canvas.drawPath(p, Paint()..color = fill);
    canvas.drawPath(
      p,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = border.withValues(alpha: 0.55),
    );
    if (accent) {
      // amber stripe across the top, fading out, like the "KEY FEATURES" box
      final w = s.width * 0.45;
      canvas.drawLine(
        Offset(tl ? c : 0, 0),
        Offset((tl ? c : 0) + w, 0),
        Paint()
          ..strokeWidth = 2
          ..shader = const LinearGradient(colors: [GipsyColors.stripe, Color(0x00EF8725)])
              .createShader(Rect.fromLTWH(0, 0, (tl ? c : 0) + w, 2)),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _ChamferPainter o) =>
      o.fill != fill || o.border != border || o.accent != accent || o.cut != cut;
}

/// Wide-tracked uppercase label, like "LOCAL AI ASSISTANT".
class TrackedLabel extends StatelessWidget {
  const TrackedLabel(this.text, {super.key, this.color = GipsyColors.steel, this.size = 11});
  final String text;
  final Color color;
  final double size;
  @override
  Widget build(BuildContext context) => Text(
    text.toUpperCase(),
    style: TextStyle(color: color, fontSize: size, letterSpacing: size * 0.28, fontWeight: FontWeight.w600),
  );
}
