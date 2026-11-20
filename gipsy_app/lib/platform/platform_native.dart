import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';

/// Where the next recorded phrase should be saved (a temp .wav file).
Future<String> newClipPath() async {
  final dir = await getTemporaryDirectory();
  return '${dir.path}${Platform.pathSeparator}gipsy_${DateTime.now().millisecondsSinceEpoch}.wav';
}

/// The bytes of a recorded phrase, so they can be sent to the hub.
Future<Uint8List> readClip(String clip) => File(clip).readAsBytes();

/// Throws a recorded phrase away once it has been used.
Future<void> deleteClip(String clip) async {
  try {
    await File(clip).delete();
  } catch (_) {}
}

/// Native apps don't need a tap before they may play sound.
Future<void> unlockAudio() async {}

/// Why the mic can't work here, or null if it can.
String? micProblem() => null;

/// Plays one sound at a time (Gipsy's voice or the kaiju song).
///
/// audioplayers plays files, so each sound is written to a temp file first.
class ClipPlayer {
  ClipPlayer() {
    if (!_contextSet) {
      // iOS: play through the loud speaker even right after recording.
      AudioPlayer.global.setAudioContext(AudioContextConfig(route: AudioContextConfigRoute.speaker).build());
      _contextSet = true;
    }
  }
  static bool _contextSet = false;

  final AudioPlayer _player = AudioPlayer();
  File? _file;

  Stream<void> get onComplete => _player.onPlayerComplete;
  Stream<Duration> get onPosition => _player.onPositionChanged;

  Future<void> play(Uint8List bytes, String ext, {Duration? position, double rate = 1.0}) async {
    _cleanUp();
    final dir = await getTemporaryDirectory();
    final f = _file = File(
      '${dir.path}${Platform.pathSeparator}gipsy_say_${DateTime.now().microsecondsSinceEpoch}$ext',
    );
    await f.writeAsBytes(bytes, flush: true);
    await _player.setPlaybackRate(rate);
    await _player.play(DeviceFileSource(f.path), position: position);
  }

  Future<void> setVolume(double v) => _player.setVolume(v);

  Future<void> stop() async {
    await _player.stop();
    await _player.setPlaybackRate(1.0);
    _cleanUp();
  }

  void _cleanUp() {
    final f = _file;
    _file = null;
    if (f != null) {
      try {
        f.deleteSync();
      } catch (_) {}
    }
  }

  void dispose() {
    _player.dispose();
    _cleanUp();
  }
}
