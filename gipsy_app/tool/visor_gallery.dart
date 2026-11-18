// Preview of all visor states side by side: flutter run -t tool/visor_gallery.dart
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
  }

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: GipsyColors.navyDeep,
        body: Center(
          child: Wrap(spacing: 56, runSpacing: 40, alignment: WrapAlignment.center, children: [
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
