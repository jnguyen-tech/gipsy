import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme.dart';

enum GipsyMode { sleeping, idle, listening, thinking, speaking }

/// Gipsy's animated head. Each mode has its own look:
///  sleeping  - visor dark, a faint slow "breath" line
///  idle      - visor lit orange, gentle shimmer
///  listening - visor brightness follows your voice, sound rings at the ears
///  thinking  - a scanner light sweeps back and forth across the visor
///  speaking  - equaliser bars in the visor bounce with Gipsy's voice
class Visor extends StatefulWidget {
  const Visor({super.key, required this.mode, required this.level, this.size = 260, this.alert = false});
  final GipsyMode mode;

  /// Kaiju alert: red-amber strobe, shaking head and hazard rings.
  final bool alert;

  /// 0..1 mic level when listening, voice level when speaking.
  final ValueNotifier<double> level;
  final double size;

  @override
  State<Visor> createState() => _VisorState();
}

class _VisorState extends State<Visor> with TickerProviderStateMixin {
  late final AnimationController _clock = AnimationController(vsync: this, duration: const Duration(seconds: 60))
    ..repeat();
  // Smooths the on/off of the visor so waking up looks like powering up.
  // Power 0..1. Going up plays the boot sequence (flicker, scan line, pods
  // lighting in order); going down plays the CRT-style shutdown.
  late final AnimationController _power = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
    reverseDuration: const Duration(milliseconds: 900),
    value: widget.mode == GipsyMode.sleeping ? 0 : 1,
  );
  // A quick bloom flash whenever the mode changes.
  late final AnimationController _flash = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 500),
    value: 1,
  );
  double _smoothLevel = 0;

  @override
  void didUpdateWidget(covariant Visor old) {
    super.didUpdateWidget(old);
    if (old.mode != widget.mode && widget.mode != GipsyMode.sleeping && old.mode != GipsyMode.sleeping) {
      _flash.forward(from: 0);
    }
    if (widget.mode == GipsyMode.sleeping) {
      _power.reverse();
    } else {
      _power.forward();
    }
  }

  @override
  void dispose() {
    _clock.dispose();
    _power.dispose();
    _flash.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: Listenable.merge([_clock, _power, _flash, widget.level]),
        builder: (context, _) {
          _smoothLevel = _smoothLevel * 0.6 + widget.level.value * 0.4;
          return CustomPaint(
            size: Size(widget.size, widget.size * 0.86),
            painter: _HelmetPainter(
              mode: widget.mode,
              t: _clock.value * 60, // seconds
              power: _power.value,
              booting: _power.status == AnimationStatus.forward,
              flash: 1 - Curves.easeOut.transform(_flash.value),
              alert: widget.alert,
              level: _smoothLevel,
            ),
          );
        },
      ),
    );
  }
}

class _HelmetPainter extends CustomPainter {
  _HelmetPainter({
    required this.mode,
    required this.t,
    required double power,
    required this.booting,
    required this.flash,
    required this.alert,
    required this.level,
  }) : rawPower = power,
       // While booting the visor flickers like a failing tube before it holds.
       power = booting && power < 0.45
           ? (_hash((t * 22).floor()) > 0.45 ? power * 1.6 : 0.04)
           : Curves.easeOut.transform(power);
  final GipsyMode mode;
  final double t;
  final double rawPower;
  final double power;
  final bool booting;
  final double flash;
  final bool alert;
  final double level;

  static double _hash(int n) {
    final x = math.sin(n * 12.9898) * 43758.5453;
    return x - x.floorToDouble();
  }

  bool get awake => mode != GipsyMode.sleeping;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final cx = w / 2;

    _paintBackdrop(canvas, size);

    // "Camera": a slow hover bob, a shake during a kaiju alert, and a slight
    // push-in while booting.
    canvas.save();
    final bob = math.sin(t * 1.1) * h * 0.012 * (awake ? 1 : 0.4);
    final shake = alert ? Offset(math.sin(t * 61) * w * 0.008, math.cos(t * 47) * h * 0.006) : Offset.zero;
    final zoom = 1 + 0.04 * (1 - Curves.easeOutCubic.transform(rawPower.clamp(0, 1))) * (booting ? 1 : 0);
    canvas.translate(cx + shake.dx, h / 2 + bob + shake.dy);
    canvas.scale(zoom);
    canvas.translate(-cx, -h / 2);

    // ---------- helmet: an ORIGINAL angular battle-mech design -------------
    // Heavy armour plates, an overhanging brow and a narrow
    // visor slit. Navy/slate + amber from John's logos. Not a copy of any film
    // or toy design: own silhouette, no centre stripe, no numbers.
    final shellRect = Offset.zero & size;
    Paint plate(List<Color> c, {Alignment begin = Alignment.topLeft, Alignment end = Alignment.bottomRight}) =>
        Paint()..shader = LinearGradient(begin: begin, end: end, colors: c).createShader(shellRect);
    final edge = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.007
      ..strokeJoin = StrokeJoin.miter
      ..color = const Color(0xFF8C9DC2).withValues(alpha: 0.75);
    final seam = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.006
      ..color = const Color(0xFF0D121D);

    // armoured collar with hazard striping
    final collar = Path()
      ..moveTo(w * 0.22, h * 0.86)
      ..lineTo(w * 0.78, h * 0.86)
      ..lineTo(w * 0.84, h * 0.99)
      ..lineTo(w * 0.16, h * 0.99)
      ..close();
    canvas.drawPath(collar, Paint()..color = const Color(0xFF262B38));
    canvas.save();
    canvas.clipPath(collar);
    for (var i = -10; i < 10; i++) {
      final x0 = cx + i * w * 0.05;
      if (i.isEven) {
        canvas.drawPath(
          Path()
            ..moveTo(x0, h * 0.99)
            ..lineTo(x0 + w * 0.025, h * 0.99)
            ..lineTo(x0 + w * 0.055, h * 0.86)
            ..lineTo(x0 + w * 0.03, h * 0.86)
            ..close(),
          Paint()..color = GipsyColors.amberDeep.withValues(alpha: 0.55),
        );
      }
    }
    canvas.restore();
    canvas.drawPath(collar, edge);

    // main skull: faceted, wide at the cheeks, tapering to a sharp jaw
    final shell = Path()
      ..moveTo(w * 0.40, h * 0.02)
      ..lineTo(w * 0.60, h * 0.02)
      ..lineTo(w * 0.78, h * 0.10)
      ..lineTo(w * 0.87, h * 0.30)
      ..lineTo(w * 0.88, h * 0.56)
      ..lineTo(w * 0.78, h * 0.76)
      ..lineTo(w * 0.60, h * 0.89)
      ..lineTo(w * 0.40, h * 0.89)
      ..lineTo(w * 0.22, h * 0.76)
      ..lineTo(w * 0.12, h * 0.56)
      ..lineTo(w * 0.13, h * 0.30)
      ..lineTo(w * 0.22, h * 0.10)
      ..close();
    canvas.drawPath(shell, plate([const Color(0xFF55688F), const Color(0xFF34446A), const Color(0xFF1A2337)]));
    canvas.drawPath(shell, edge);

    // crown plate: a raised, lighter facet on top
    final crown = Path()
      ..moveTo(w * 0.40, h * 0.02)
      ..lineTo(w * 0.60, h * 0.02)
      ..lineTo(w * 0.66, h * 0.22)
      ..lineTo(cx, h * 0.27)
      ..lineTo(w * 0.34, h * 0.22)
      ..close();
    canvas.drawPath(
      crown,
      plate(
        [const Color(0xFF6E81AA), const Color(0xFF41527A)],
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
      ),
    );
    canvas.drawPath(crown, edge);
    // twin amber running lights on the crown
    for (final side in [-1.0, 1.0]) {
      canvas.drawLine(
        Offset(cx + side * w * 0.05, h * 0.07),
        Offset(cx + side * w * 0.065, h * 0.19),
        Paint()
          ..strokeWidth = w * 0.012
          ..strokeCap = StrokeCap.round
          ..color = GipsyColors.amber.withValues(alpha: 0.2 + 0.7 * power),
      );
    }

    // side armour slabs (temples) with vents
    for (final side in [-1.0, 1.0]) {
      double x(double f) => cx + side * w * f;
      final slab = Path()
        ..moveTo(x(0.23), h * 0.12)
        ..lineTo(x(0.37), h * 0.30)
        ..lineTo(x(0.38), h * 0.56)
        ..lineTo(x(0.30), h * 0.66)
        ..lineTo(x(0.37), h * 0.30)
        ..close();
      canvas.drawPath(slab, Paint()..color = Colors.black.withValues(alpha: 0.18));
      for (var i = 0; i < 3; i++) {
        canvas.drawLine(
          Offset(x(0.27 + i * 0.03), h * 0.20 + i * h * 0.02),
          Offset(x(0.30 + i * 0.03), h * 0.30),
          seam..strokeWidth = w * 0.009,
        );
      }
    }
    seam.strokeWidth = w * 0.006;

    // jaw: sharp chin guard with intake slits
    final jaw = Path()
      ..moveTo(w * 0.27, h * 0.66)
      ..lineTo(w * 0.73, h * 0.66)
      ..lineTo(w * 0.62, h * 0.86)
      ..lineTo(w * 0.38, h * 0.86)
      ..close();
    canvas.drawPath(
      jaw,
      plate(
        [const Color(0xFF2E3B5C), const Color(0xFF151C2C)],
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
      ),
    );
    canvas.drawPath(jaw, edge);
    for (var i = 0; i < 5; i++) {
      final x = cx + (i - 2) * w * 0.045;
      canvas.drawLine(
        Offset(x, h * 0.71),
        Offset(x + (i - 2) * w * 0.006, h * 0.81),
        Paint()
          ..strokeWidth = w * 0.014
          ..strokeCap = StrokeCap.round
          ..color = const Color(0xFF0A0E16),
      );
    }

    // battle scratches
    final scratch = Paint()
      ..strokeWidth = w * 0.004
      ..color = const Color(0xFFB8C3DD).withValues(alpha: 0.35);
    canvas.drawLine(Offset(w * 0.70, h * 0.12), Offset(w * 0.76, h * 0.20), scratch);
    canvas.drawLine(Offset(w * 0.72, h * 0.13), Offset(w * 0.765, h * 0.185), scratch);
    canvas.drawLine(Offset(w * 0.20, h * 0.62), Offset(w * 0.25, h * 0.66), scratch);

    // side sensor pods (light up and send rings when listening)
    for (final side in [-1.0, 1.0]) {
      final c = Offset(cx + side * w * 0.43, h * 0.47);
      final hex = Path();
      for (var k = 0; k < 6; k++) {
        final ang = math.pi / 6 + k * math.pi / 3;
        final pt = c + Offset(math.cos(ang), math.sin(ang)) * (w * 0.055);
        if (k == 0) {
          hex.moveTo(pt.dx, pt.dy);
        } else {
          hex.lineTo(pt.dx, pt.dy);
        }
      }
      hex.close();
      canvas.drawPath(hex, Paint()..color = const Color(0xFF1C2438));
      canvas.drawPath(hex, edge);
      final podOn = booting ? ((rawPower - (side < 0 ? 0.45 : 0.6)) / 0.15).clamp(0.0, 1.0) : 1.0;
      final glow = mode == GipsyMode.sleeping
          ? 0.08
          : (0.35 + 0.65 * power * (mode == GipsyMode.listening ? level : 0.3)) * podOn;
      canvas.drawCircle(c, w * 0.02, Paint()..color = GipsyColors.amber.withValues(alpha: glow));

      if (mode == GipsyMode.listening) {
        for (var k = 0; k < 3; k++) {
          final phase = ((t * 1.2) + k / 3) % 1.0;
          final r = w * (0.07 + phase * 0.13);
          canvas.drawArc(
            Rect.fromCircle(center: c, radius: r),
            side < 0 ? math.pi * 0.70 : -math.pi * 0.30,
            math.pi * 0.60,
            false,
            Paint()
              ..style = PaintingStyle.stroke
              ..strokeWidth = w * 0.008
              ..color = GipsyColors.amber.withValues(alpha: (1 - phase) * (0.3 + level * 0.7)),
          );
        }
      }
    }

    // ---------- visor: a narrow armoured slit under a heavy brow -------------
    final visor = Path()
      ..moveTo(w * 0.17, h * 0.38)
      ..lineTo(w * 0.83, h * 0.38)
      ..lineTo(w * 0.79, h * 0.54)
      ..lineTo(w * 0.62, h * 0.58)
      ..lineTo(w * 0.38, h * 0.58)
      ..lineTo(w * 0.21, h * 0.54)
      ..close();
    canvas.drawPath(
      visor,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.03
        ..strokeJoin = StrokeJoin.miter
        ..color = const Color(0xFF111725),
    );
    final vRect = visor.getBounds();

    // dark glass
    canvas.drawPath(visor, Paint()..color = const Color(0xFF05070D));

    canvas.save();
    canvas.clipPath(visor);

    switch (mode) {
      case GipsyMode.sleeping:
        // Shutdown: the glow collapses to a bright line, then a dot, like an
        // old CRT switching off.
        if (rawPower > 0.01) {
          final p = Curves.easeIn.transform(rawPower);
          final r = Rect.fromCenter(
            center: vRect.center,
            width: vRect.width * (p > 0.35 ? 1.0 : 0.05 + p / 0.35 * 0.95),
            height: vRect.height * math.max(0.06, (p - 0.35).clamp(0.0, 1.0) / 0.65),
          );
          canvas.drawRRect(
            RRect.fromRectAndRadius(r, Radius.circular(r.height / 2)),
            Paint()
              ..color = Color.lerp(GipsyColors.amber, Colors.white, 1 - p)!.withValues(alpha: 0.95)
              ..maskFilter = MaskFilter.blur(BlurStyle.normal, w * 0.01),
          );
          break;
        }
        // A barely-there line that breathes slowly, like a standby LED.
        final breathe = 0.10 + 0.08 * (0.5 + 0.5 * math.sin(t * 1.3));
        _glowBar(
          canvas,
          Rect.fromCenter(center: vRect.center, width: vRect.width * 0.5, height: vRect.height * 0.08),
          GipsyColors.navyGlow.withValues(alpha: breathe),
        );
        break;

      case GipsyMode.idle:
        _fill(canvas, vRect, 0.80 * power);
        // slow shimmer sweeping across
        final x = vRect.left + ((t * 0.25) % 1.4 - 0.2) * vRect.width;
        canvas.drawRect(
          vRect,
          Paint()
            ..shader = LinearGradient(
              colors: [
                Colors.white.withValues(alpha: 0),
                Colors.white.withValues(alpha: 0.25 * power),
                Colors.white.withValues(alpha: 0),
              ],
            ).createShader(Rect.fromLTWH(x - 30, vRect.top, 60, vRect.height)),
        );
        break;

      case GipsyMode.listening:
        // dim glow + a live waveform that follows your voice
        _fill(canvas, vRect, power * (0.20 + 0.25 * level));
        final wave = Path();
        final amp = vRect.height * (0.06 + 0.40 * level);
        for (var i = 0; i <= 80; i++) {
          final f = i / 80;
          final env = math.sin(f * math.pi); // taper at the ends
          final y = vRect.center.dy + amp * env * (math.sin(f * 14 + t * 9) * 0.7 + math.sin(f * 31 - t * 13) * 0.3);
          final x = vRect.left + vRect.width * f;
          if (i == 0) {
            wave.moveTo(x, y);
          } else {
            wave.lineTo(x, y);
          }
        }
        canvas.drawPath(
          wave,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = w * 0.02
            ..color = GipsyColors.amber.withValues(alpha: 0.6 * power)
            ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4),
        );
        canvas.drawPath(
          wave,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = w * 0.008
            ..color = GipsyColors.amberHot.withValues(alpha: power),
        );
        break;

      case GipsyMode.thinking:
        _fill(canvas, vRect, 0.25 * power);
        // scanner light that sweeps side to side with a trail
        final p = 0.5 + 0.5 * math.sin(t * 3.2);
        for (var i = 0; i < 8; i++) {
          final lag = 0.5 + 0.5 * math.sin(t * 3.2 - i * 0.12);
          final x = vRect.left + vRect.width * (0.08 + 0.84 * lag);
          canvas.drawCircle(
            Offset(x, vRect.center.dy),
            vRect.height * (0.42 - i * 0.03),
            Paint()
              ..color = GipsyColors.amberHot.withValues(alpha: (0.9 - i * 0.11) * power)
              ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6),
          );
        }
        final x = vRect.left + vRect.width * (0.08 + 0.84 * p);
        canvas.drawCircle(
          Offset(x, vRect.center.dy),
          vRect.height * 0.22,
          Paint()..color = Colors.white.withValues(alpha: 0.9 * power),
        );
        break;

      case GipsyMode.speaking:
        _fill(canvas, vRect, 0.30 * power);
        // equaliser bars, tallest in the middle, driven by the voice
        const bars = 11;
        final bw = vRect.width / (bars * 1.5);
        for (var i = 0; i < bars; i++) {
          final centre = 1 - ((i - (bars - 1) / 2).abs() / (bars / 2));
          final wobble = 0.55 + 0.45 * math.sin(t * 17 + i * 1.7);
          final amp = (0.18 + 0.82 * math.sqrt(level) * (0.45 + 0.55 * centre) * wobble).clamp(0.12, 1.0);
          final bh = vRect.height * 0.92 * amp;
          final x = vRect.left + vRect.width * 0.1 + i * (vRect.width * 0.8 / (bars - 1));
          canvas.drawRRect(
            RRect.fromRectAndRadius(
              Rect.fromCenter(center: Offset(x, vRect.center.dy), width: bw, height: bh),
              Radius.circular(bw / 2),
            ),
            Paint()..color = Color.lerp(GipsyColors.amber, Colors.white, amp * 0.6)!.withValues(alpha: power),
          );
        }
        break;
    }

    // boot: a bright scan line sweeps down the glass
    if (booting && rawPower > 0.3 && rawPower < 0.95) {
      final y = vRect.top + vRect.height * ((rawPower - 0.3) / 0.65);
      canvas.drawRect(
        Rect.fromLTWH(vRect.left, y - vRect.height * 0.08, vRect.width, vRect.height * 0.16),
        Paint()
          ..color = Colors.white.withValues(alpha: 0.85)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, w * 0.008),
      );
    }
    // kaiju alert: the glass strobes red-amber
    if (alert && awake) {
      final strobe = (math.sin(t * 9) > 0) ? 0.55 : 0.15;
      canvas.drawRect(vRect, Paint()..color = const Color(0xFFFF3B1F).withValues(alpha: strobe));
    }
    // bloom flash on a mode change
    if (flash > 0.01 && awake) {
      canvas.drawRect(vRect, Paint()..color = Colors.white.withValues(alpha: 0.5 * flash));
    }

    // scan lines on the glass
    final scan = Paint()..color = Colors.black.withValues(alpha: 0.18);
    for (var y = vRect.top; y < vRect.bottom; y += 3) {
      canvas.drawLine(Offset(vRect.left, y), Offset(vRect.right, y), scan);
    }
    canvas.restore();

    // outer glow bleeding onto the helmet when lit
    if (mode != GipsyMode.sleeping) {
      final glow = switch (mode) {
        GipsyMode.listening => 0.25 + 0.5 * level,
        GipsyMode.speaking => 0.25 + 0.45 * level,
        GipsyMode.thinking => 0.25,
        _ => 0.4,
      };
      canvas.drawPath(
        visor,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = w * 0.02
          ..color = (alert ? const Color(0xFFFF5A1F) : GipsyColors.amber).withValues(
            alpha: ((glow + 0.5 * flash) * power).clamp(0.0, 1.0),
          )
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, w * (0.04 + 0.03 * flash)),
      );
    }
    // heavy brow plate overhanging the visor (drawn last, on top)
    final brow = Path()
      ..moveTo(w * 0.13, h * 0.30)
      ..lineTo(w * 0.87, h * 0.30)
      ..lineTo(w * 0.85, h * 0.37)
      ..lineTo(w * 0.60, h * 0.40)
      ..lineTo(cx, h * 0.43)
      ..lineTo(w * 0.40, h * 0.40)
      ..lineTo(w * 0.15, h * 0.37)
      ..close();
    canvas.drawPath(
      brow,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFF6A7DA6), Color(0xFF2C3A5C)],
        ).createShader(Rect.fromLTWH(0, h * 0.30, w, h * 0.13)),
    );
    canvas.drawPath(
      brow,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.007
        ..color = const Color(0xFF8C9DC2).withValues(alpha: 0.75),
    );
    canvas.drawPath(
      visor,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.01
        ..color = GipsyColors.armorEdge,
    );
    canvas.restore();

    _paintHud(canvas, size);
  }

  /// Behind the head: a soft glow, slowly turning holographic rings and
  /// drifting embers. Rings spin faster while thinking; everything turns
  /// red-amber in a kaiju alert.
  void _paintBackdrop(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final c = Offset(w / 2, h * 0.48);
    final tint = alert ? const Color(0xFFFF4A1F) : (awake ? GipsyColors.amber : GipsyColors.navyGlow);
    final energy = awake ? (0.35 + 0.65 * power) : 0.25;

    // halo
    final pulse = 0.5 + 0.5 * math.sin(t * (alert ? 9 : 1.4));
    canvas.drawCircle(
      c,
      w * 0.62,
      Paint()
        ..shader = RadialGradient(
          colors: [
            tint.withValues(alpha: (0.10 + 0.10 * pulse + 0.25 * level * (awake ? 1 : 0)) * energy),
            tint.withValues(alpha: 0),
          ],
        ).createShader(Rect.fromCircle(center: c, radius: w * 0.62)),
    );

    // holographic rings: dashed arcs turning in opposite directions
    final spin = mode == GipsyMode.thinking ? 2.4 : (alert ? 3.0 : 0.25);
    for (var ring = 0; ring < 3; ring++) {
      final r = w * (0.50 + ring * 0.07);
      final dir = ring.isEven ? 1 : -1;
      final segs = 10 + ring * 6;
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * (0.006 - ring * 0.0012)
        ..color = tint.withValues(alpha: (0.22 - ring * 0.05) * energy);
      for (var i = 0; i < segs; i++) {
        if ((i + ring) % 3 == 0) continue;
        final a0 = dir * t * spin * (0.5 + ring * 0.25) + i * 2 * math.pi / segs;
        canvas.drawArc(Rect.fromCircle(center: c, radius: r), a0, 2 * math.pi / segs * 0.6, false, paint);
      }
    }
    // tick marks on the inner ring, like a targeting reticle
    final tick = Paint()
      ..strokeWidth = w * 0.004
      ..color = tint.withValues(alpha: 0.35 * energy);
    for (var i = 0; i < 4; i++) {
      final a = i * math.pi / 2 + t * spin * 0.3;
      final d = Offset(math.cos(a), math.sin(a));
      canvas.drawLine(c + d * (w * 0.44), c + d * (w * 0.48), tick);
    }

    // drifting embers rising past the head
    final ember = Paint();
    for (var i = 0; i < 26; i++) {
      final seed = _hash(i * 7 + 3);
      final speed = 0.04 + 0.06 * _hash(i * 13 + 1) * (alert ? 3 : 1);
      final life = (t * speed + seed) % 1.0;
      final x = w * (0.05 + 0.9 * _hash(i * 31 + 5)) + math.sin(t * 0.7 + i) * w * 0.02;
      final y = h * (1.05 - life * 1.15);
      final a = math.sin(life * math.pi) * (0.25 + 0.5 * _hash(i * 17)) * energy;
      ember.color = tint.withValues(alpha: a);
      canvas.drawCircle(Offset(x, y), w * (0.003 + 0.004 * _hash(i * 5)), ember);
    }
  }

  /// Corner brackets that snap in during boot, like a targeting HUD.
  void _paintHud(Canvas canvas, Size size) {
    if (!awake && rawPower < 0.01) return;
    final w = size.width, h = size.height;
    final settle = Curves.easeOutBack.transform(rawPower.clamp(0.0, 1.0));
    final inset = w * (0.02 + 0.10 * (1 - settle));
    final len = w * 0.08;
    final col = (alert ? const Color(0xFFFF4A1F) : GipsyColors.amber).withValues(
      alpha: (booting ? 0.9 : 0.35) * rawPower.clamp(0.0, 1.0),
    );
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.006
      ..color = col;
    final r = Rect.fromLTRB(inset, inset * 0.6, w - inset, h - inset * 0.6);
    for (final corner in [r.topLeft, r.topRight, r.bottomLeft, r.bottomRight]) {
      final sx = corner.dx < w / 2 ? 1.0 : -1.0;
      final sy = corner.dy < h / 2 ? 1.0 : -1.0;
      canvas.drawPath(
        Path()
          ..moveTo(corner.dx, corner.dy + sy * len)
          ..lineTo(corner.dx, corner.dy)
          ..lineTo(corner.dx + sx * len, corner.dy),
        p,
      );
    }
  }

  void _fill(Canvas canvas, Rect r, double a) {
    canvas.drawRect(
      r,
      Paint()
        ..shader = RadialGradient(
          colors: [
            GipsyColors.amberHot.withValues(alpha: a.clamp(0, 1)),
            GipsyColors.amber.withValues(alpha: (a * 0.75).clamp(0, 1)),
            GipsyColors.amberDeep.withValues(alpha: (a * 0.55).clamp(0, 1)),
          ],
          radius: 1.2,
        ).createShader(r),
    );
  }

  void _glowBar(Canvas canvas, Rect r, Color c) {
    canvas.drawRRect(
      RRect.fromRectAndRadius(r, Radius.circular(r.height)),
      Paint()
        ..color = c
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
    );
  }

  @override
  bool shouldRepaint(covariant _HelmetPainter old) => true;
}

/// The Reactor Core logo, spinning, used as the "AI is working" indicator.
class ReactorSpinner extends StatefulWidget {
  const ReactorSpinner({super.key, this.size = 28, this.active = true});
  final double size;
  final bool active;
  @override
  State<ReactorSpinner> createState() => _ReactorSpinnerState();
}

class _ReactorSpinnerState extends State<ReactorSpinner> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 2))..repeat();
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final img = ClipOval(
      child: Image.asset('assets/brand/reactor_core.png', width: widget.size, height: widget.size, fit: BoxFit.cover),
    );
    if (!widget.active) return Opacity(opacity: 0.35, child: img);
    return AnimatedBuilder(
      animation: _c,
      builder: (_, child) => Transform.rotate(
        angle: _c.value * 2 * math.pi,
        child: Container(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            boxShadow: [
              BoxShadow(
                color: GipsyColors.amber.withValues(alpha: 0.35 + 0.3 * math.sin(_c.value * 2 * math.pi).abs()),
                blurRadius: widget.size * 0.6,
              ),
            ],
          ),
          child: child,
        ),
      ),
      child: img,
    );
  }
}
