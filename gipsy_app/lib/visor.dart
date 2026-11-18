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
  const Visor({super.key, required this.mode, required this.level, this.size = 260});
  final GipsyMode mode;

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
  late final AnimationController _power = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 700),
    value: widget.mode == GipsyMode.sleeping ? 0 : 1,
  );
  double _smoothLevel = 0;

  @override
  void didUpdateWidget(covariant Visor old) {
    super.didUpdateWidget(old);
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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: Listenable.merge([_clock, _power, widget.level]),
        builder: (context, _) {
          _smoothLevel = _smoothLevel * 0.6 + widget.level.value * 0.4;
          return CustomPaint(
            size: Size(widget.size, widget.size * 0.86),
            painter: _HelmetPainter(
              mode: widget.mode,
              t: _clock.value * 60, // seconds
              power: Curves.easeOut.transform(_power.value),
              level: _smoothLevel,
            ),
          );
        },
      ),
    );
  }
}

class _HelmetPainter extends CustomPainter {
  _HelmetPainter({required this.mode, required this.t, required this.power, required this.level});
  final GipsyMode mode;
  final double t;
  final double power;
  final double level;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final cx = w / 2;

    // ---------- helmet: an ORIGINAL rounded chibi design -------------------
    // Big rounded dome, wraparound visor band and a collar ring. Colours are
    // the navy/slate + amber of John's logos. Deliberately not a copy of any
    // film or toy design: no centre stripe, no numbers, its own visor shape.
    final shellRect = Offset.zero & size;

    // collar ring under the head
    final collar = RRect.fromRectAndRadius(
      Rect.fromCenter(center: Offset(cx, h * 0.93), width: w * 0.62, height: h * 0.11),
      Radius.circular(h * 0.05),
    );
    canvas.drawRRect(collar, Paint()..color = const Color(0xFF2A2F3D));
    canvas.drawRRect(
      collar,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.008
        ..color = GipsyColors.armorEdge.withValues(alpha: 0.8),
    );
    for (var i = -3; i <= 3; i++) {
      final x = cx + i * w * 0.07;
      canvas.drawLine(
        Offset(x, h * 0.895),
        Offset(x, h * 0.965),
        Paint()
          ..strokeWidth = w * 0.006
          ..color = const Color(0xFF171B25),
      );
    }

    // dome: tall rounded shell, widest at the cheeks
    final shell = Path()
      ..moveTo(cx, h * 0.02)
      ..cubicTo(w * 0.80, h * 0.02, w * 0.92, h * 0.26, w * 0.90, h * 0.52)
      ..cubicTo(w * 0.89, h * 0.70, w * 0.80, h * 0.84, w * 0.66, h * 0.89)
      ..lineTo(w * 0.34, h * 0.89)
      ..cubicTo(w * 0.20, h * 0.84, w * 0.11, h * 0.70, w * 0.10, h * 0.52)
      ..cubicTo(w * 0.08, h * 0.26, w * 0.20, h * 0.02, cx, h * 0.02)
      ..close();
    canvas.drawPath(
      shell,
      Paint()
        ..shader = const RadialGradient(
          center: Alignment(-0.35, -0.55),
          radius: 1.05,
          colors: [Color(0xFF5A6F99), Color(0xFF3B4D73), Color(0xFF243150), Color(0xFF151C2E)],
          stops: [0, 0.35, 0.75, 1],
        ).createShader(shellRect),
    );
    canvas.drawPath(
      shell,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.012
        ..color = const Color(0xFF6F82AA).withValues(alpha: 0.8),
    );

    // specular highlight on the dome
    canvas.drawOval(
      Rect.fromCenter(center: Offset(w * 0.36, h * 0.13), width: w * 0.22, height: h * 0.07),
      Paint()
        ..color = Colors.white.withValues(alpha: 0.10)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, w * 0.02),
    );

    final seam = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w * 0.006
      ..color = const Color(0xFF121827);

    // brow plate: two panel arcs over the visor
    for (final f in [0.27, 0.22]) {
      canvas.drawArc(
        Rect.fromCenter(center: Offset(cx, h * 0.40), width: w * (0.70 + f * 0.2), height: h * f * 2),
        math.pi * 1.08,
        math.pi * 0.84,
        false,
        seam,
      );
    }

    // temple vents with small amber accent lights (one each side)
    for (final side in [-1.0, 1.0]) {
      for (var i = 0; i < 3; i++) {
        final x = cx + side * w * (0.20 + i * 0.045);
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(center: Offset(x, h * 0.17 + i * h * 0.015), width: w * 0.025, height: h * 0.07),
            Radius.circular(w * 0.01),
          ),
          Paint()..color = const Color(0xFF151B2A),
        );
      }
      canvas.drawCircle(
        Offset(cx + side * w * 0.11, h * 0.235),
        w * 0.012,
        Paint()..color = GipsyColors.amber.withValues(alpha: 0.25 + 0.65 * power),
      );
    }

    // jaw guard: rounded chin plate with a grille
    final jaw = Path()
      ..moveTo(w * 0.24, h * 0.68)
      ..quadraticBezierTo(cx, h * 0.62, w * 0.76, h * 0.68)
      ..lineTo(w * 0.66, h * 0.86)
      ..quadraticBezierTo(cx, h * 0.90, w * 0.34, h * 0.86)
      ..close();
    canvas.drawPath(jaw, Paint()..color = Colors.black.withValues(alpha: 0.20));
    canvas.drawPath(jaw, seam);
    for (var i = 0; i < 4; i++) {
      final y = h * (0.73 + i * 0.03);
      canvas.drawLine(Offset(cx - w * 0.10, y), Offset(cx + w * 0.10, y), seam);
    }

    // side comm pods (light up and send rings when listening)
    for (final side in [-1.0, 1.0]) {
      final c = Offset(cx + side * w * 0.455, h * 0.55);
      canvas.drawCircle(c, w * 0.06, Paint()..color = const Color(0xFF263252));
      canvas.drawCircle(
        c,
        w * 0.06,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = w * 0.009
          ..color = const Color(0xFF6F82AA),
      );
      final glow = mode == GipsyMode.sleeping
          ? 0.08
          : 0.35 + 0.65 * power * (mode == GipsyMode.listening ? level : 0.3);
      canvas.drawCircle(c, w * 0.022, Paint()..color = GipsyColors.amber.withValues(alpha: glow));

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

    // ---------- visor: one smooth wraparound band ---------------------------
    final visor = Path()
      ..moveTo(w * 0.14, h * 0.40)
      ..quadraticBezierTo(cx, h * 0.31, w * 0.86, h * 0.40)
      ..quadraticBezierTo(w * 0.885, h * 0.50, w * 0.83, h * 0.58)
      ..quadraticBezierTo(cx, h * 0.52, w * 0.17, h * 0.58)
      ..quadraticBezierTo(w * 0.115, h * 0.50, w * 0.14, h * 0.40)
      ..close();
    // dark rim around the glass
    canvas.drawPath(
      visor,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.035
        ..strokeJoin = StrokeJoin.round
        ..color = const Color(0xFF1A2133),
    );
    final vRect = visor.getBounds();

    // dark glass
    canvas.drawPath(visor, Paint()..color = const Color(0xFF05070D));

    canvas.save();
    canvas.clipPath(visor);

    switch (mode) {
      case GipsyMode.sleeping:
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
          ..color = GipsyColors.amber.withValues(alpha: glow * power)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, w * 0.04),
      );
    }
    canvas.drawPath(
      visor,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = w * 0.01
        ..color = GipsyColors.armorEdge,
    );
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
