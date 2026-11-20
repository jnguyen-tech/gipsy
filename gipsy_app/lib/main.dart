import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'brain.dart';
import 'home_page.dart';
import 'platform/platform.dart';
import 'settings.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = GipsySettings();
  await settings.load();
  runApp(GipsyApp(settings: settings));
}

class GipsyApp extends StatefulWidget {
  const GipsyApp({super.key, required this.settings});
  final GipsySettings settings;

  @override
  State<GipsyApp> createState() => _GipsyAppState();
}

class _GipsyAppState extends State<GipsyApp> with WidgetsBindingObserver {
  late final GipsyBrain brain = GipsyBrain(widget.settings);

  /// The web version waits for one tap before it starts (see [_TapToStart]).
  bool _started = !kIsWeb;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (_started) brain.start();
  }

  Future<void> _startFromTap() async {
    // This must run inside the tap, or Safari keeps Gipsy silent.
    await unlockAudio();
    setState(() => _started = true);
    brain.start();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_started) return;
    // On the phone, let go of the mic when the app is in the background.
    if (state == AppLifecycleState.paused) brain.pause();
    if (state == AppLifecycleState.resumed) brain.resume();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    brain.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Gipsy',
      debugShowCheckedModeBanner: false,
      theme: gipsyTheme(),
      home: _started ? HomePage(brain: brain) : _TapToStart(onStart: _startFromTap),
    );
  }
}

/// Web only: a "tap to start" screen.
///
/// Safari won't let a web page play sound until you tap something, and it
/// asks for the mic at the same moment. One tap here unlocks both, so Gipsy
/// can answer out loud afterwards.
class _TapToStart extends StatelessWidget {
  const _TapToStart({required this.onStart});
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    return GipsyBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: InkWell(
          onTap: onStart,
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(24),
                  child: Image.asset('assets/brand/armored_visor.png', width: 132, height: 132),
                ),
                const SizedBox(height: 28),
                const Text(
                  'GIPSY',
                  style: TextStyle(
                    letterSpacing: 8,
                    fontWeight: FontWeight.w800,
                    fontSize: 30,
                    color: GipsyColors.steelBright,
                  ),
                ),
                const SizedBox(height: 10),
                const TrackedLabel('Tap to wake Gipsy', size: 11),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
