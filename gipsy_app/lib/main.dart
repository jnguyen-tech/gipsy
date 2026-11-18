import 'package:flutter/material.dart';

import 'brain.dart';
import 'home_page.dart';
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    brain.start();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
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
      home: HomePage(brain: brain),
    );
  }
}
