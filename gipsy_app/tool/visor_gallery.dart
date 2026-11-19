// Preview of all visor states side by side: flutter run -t tool/visor_gallery.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:gipsy/theme.dart';
import 'package:gipsy/visor.dart';

void main() => runApp(const MaterialApp(debugShowCheckedModeBanner: false, home: _Gallery()));

class _Gallery extends StatefulWidget {
  const _Gallery();
  @override
  State<_Gallery> createState() => _GalleryState();
}

class _GalleryState extends State<_Gallery> with SingleTickerProviderStateMixin {
  final level = ValueNotifier(0.0);
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900))
    ..addListener(() => level.value = 0.3 + 0.7 * Curves.easeInOut.transform((c.value * 2 - 1).abs()))
    ..repeat();
  @override
  void initState() {
    super.initState();
    c.value; // start the fake voice level
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => setState(() => _awake = !_awake));
  }

  bool _awake = false;
  late final Timer _timer;

  @override
  void dispose() {
    _timer.cancel();
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: GipsyColors.navyDeep,
        body: Center(
          child: Wrap(spacing: 70, runSpacing: 60, alignment: WrapAlignment.center, children: [
            // Boot + shutdown demo: wakes and sleeps every 3 seconds.
            Column(mainAxisSize: MainAxisSize.min, children: [
              Visor(mode: _awake ? GipsyMode.idle : GipsyMode.sleeping, level: level, size: 220),
              const SizedBox(height: 8),
              const Text('BOOT / SHUTDOWN',
                  style: TextStyle(color: GipsyColors.amber, letterSpacing: 3, fontWeight: FontWeight.bold)),
            ]),
            Column(mainAxisSize: MainAxisSize.min, children: [
              Visor(mode: GipsyMode.speaking, level: level, size: 220, alert: true),
              const SizedBox(height: 8),
              const Text('KAIJU ALERT',
                  style: TextStyle(color: Color(0xFFFF4A1F), letterSpacing: 3, fontWeight: FontWeight.bold)),
            ]),
            for (final m in GipsyMode.values)
              Column(mainAxisSize: MainAxisSize.min, children: [
                Visor(mode: m, level: level, size: 220),
                const SizedBox(height: 8),
                Text(m.name.toUpperCase(),
                    style: const TextStyle(color: GipsyColors.amber, letterSpacing: 3, fontWeight: FontWeight.bold)),
              ]),
          ]),
        ),
      );
}
