/// The few things that work differently in a browser than in the native apps:
/// where recorded clips live, how sound is played, and whether the mic is
/// allowed at all.
///
/// Dart picks one of the two files below when the app is built:
///   - platform_native.dart for Windows, iPhone, Android, Mac and Linux
///   - platform_web.dart    for the web version (Safari "Add to Home Screen")
library;

export 'platform_native.dart' if (dart.library.js_interop) 'platform_web.dart';
