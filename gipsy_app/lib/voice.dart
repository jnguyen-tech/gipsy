import 'dart:async';
import 'dart:io';
import 'dart:math' as math;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Gipsy's ears: records the mic and cuts out one spoken phrase at a time.
///
/// It is a simple loudness-based "voice activity detector": it learns how
/// loud the room is, waits for sound clearly above that, and stops a moment
/// after you go quiet. The phrase is saved as a 16 kHz WAV for the hub.
class Ears {
  final AudioRecorder _rec = AudioRecorder();
  StreamSubscription<Amplitude>? _ampSub;
  Completer<String?>? _done;
  bool _busy = false;

  /// Live mic level 0..1, for the listening animation.
  final ValueNotifier<double> level = ValueNotifier(0);

  double _noiseFloor = -50; // dBFS, adapts to the room
  bool get isRecording => _busy;

  Future<bool> hasPermission() => _rec.hasPermission();

  /// Records until a phrase ends.
  ///
  /// [waitForSpeech]: give up (return null) if nobody speaks within this time.
  /// [maxPhrase]: hard cap on one phrase.
  Future<String?> listenOnce({
    Duration waitForSpeech = const Duration(seconds: 8),
    Duration maxPhrase = const Duration(seconds: 15),
    Duration endSilence = const Duration(milliseconds: 900),
  }) async {
    if (_busy) await stop();
    _busy = true;
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}${Platform.pathSeparator}gipsy_${DateTime.now().millisecondsSinceEpoch}.wav';
    await _rec.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
      ),
      path: path,
    );

    final done = _done = Completer<String?>();
    final started = DateTime.now();
    DateTime? speechStart;
    DateTime lastLoud = DateTime.now();

    _ampSub = _rec.onAmplitudeChanged(const Duration(milliseconds: 80)).listen((a) {
      final db = a.current.isFinite ? a.current.clamp(-90.0, 0.0) : -90.0;
      final threshold = math.max(_noiseFloor + 12, -48.0);
      final loud = db > threshold;
      level.value = ((db - _noiseFloor) / 35).clamp(0.0, 1.0);
      final now = DateTime.now();
      if (!loud && speechStart == null) {
        // Only learn the room noise while nobody is talking.
        _noiseFloor = _noiseFloor * 0.95 + db * 0.05;
      }
      if (loud) {
        lastLoud = now;
        speechStart ??= now;
      }
      if (speechStart == null && now.difference(started) > waitForSpeech) {
        _finish(null);
      } else if (speechStart != null &&
          (now.difference(lastLoud) > endSilence || now.difference(speechStart!) > maxPhrase)) {
        // Ignore tiny clicks shorter than ~0.3 s.
        final spoke = lastLoud.difference(speechStart!) > const Duration(milliseconds: 300);
        _finish(spoke ? path : null);
      }
    });
    return done.future;
  }

  Future<void> _finish(String? path) async {
    final done = _done;
    if (done == null || done.isCompleted) return;
    await _ampSub?.cancel();
    _ampSub = null;
    final saved = await _rec.stop();
    _busy = false;
    level.value = 0;
    if (path == null && saved != null) {
      try {
        File(saved).deleteSync();
      } catch (_) {}
    }
    done.complete(path);
  }

  /// Stop listening right now (nothing is returned).
  Future<void> stop() => _finish(null);

  Future<void> dispose() async {
    await stop();
    await _rec.dispose();
  }
}

/// Gipsy's mouth: plays WAV clips one after another and exposes a live
/// loudness envelope so the visor can move in time with the words.
class Mouth {
  Mouth() {
    // iOS: play through the loud speaker even right after recording.
    AudioPlayer.global.setAudioContext(AudioContextConfig(route: AudioContextConfigRoute.speaker).build());
    _player.onPositionChanged.listen((p) {
      final env = _env;
      if (env == null || env.isEmpty) return;
      final i = (p.inMilliseconds / _envStepMs).floor();
      level.value = i < env.length ? env[i] : 0;
    });
  }

  final AudioPlayer _player = AudioPlayer();
  final List<Uint8List> _queue = [];
  bool _playing = false;
  Completer<void>? _allDone;
  List<double>? _env;
  static const _envStepMs = 40;

  /// 0..1 loudness of what's being said right now.
  final ValueNotifier<double> level = ValueNotifier(0);
  final ValueNotifier<bool> speaking = ValueNotifier(false);

  void enqueue(Uint8List wav) {
    _queue.add(wav);
    _allDone ??= Completer<void>();
    if (!_playing) _next();
  }

  /// Completes once everything queued so far has been spoken.
  Future<void> get finished => _allDone?.future ?? Future.value();

  Future<void> _next() async {
    if (_queue.isEmpty) {
      _playing = false;
      speaking.value = false;
      level.value = 0;
      final c = _allDone;
      _allDone = null;
      c?.complete();
      return;
    }
    _playing = true;
    speaking.value = true;
    final wav = _queue.removeAt(0);
    _env = _envelope(wav);
    final dir = await getTemporaryDirectory();
    final f = File('${dir.path}${Platform.pathSeparator}gipsy_say_${DateTime.now().microsecondsSinceEpoch}.wav');
    await f.writeAsBytes(wav, flush: true);
    final done = Completer<void>();
    late final StreamSubscription sub;
    sub = _player.onPlayerComplete.listen((_) {
      if (!done.isCompleted) done.complete();
    });
    try {
      await _player.play(DeviceFileSource(f.path));
      // Safety net in case the completion event never fires.
      await done.future.timeout(_duration(wav) + const Duration(seconds: 2), onTimeout: () {});
    } catch (e) {
      debugPrint('Playback failed: $e');
    } finally {
      await sub.cancel();
      try {
        f.deleteSync();
      } catch (_) {}
    }
    _next();
  }

  Timer? _musicPulse;

  /// Plays a music file (the kaiju battle song) at [rate] (0.85 = slowed).
  /// The visor bounces to a steady beat while it plays.
  Future<void> playMusic(Uint8List bytes, String ext, {double rate = 1.0}) async {
    await finished;
    final dir = await getTemporaryDirectory();
    final f = File('${dir.path}${Platform.pathSeparator}gipsy_song$ext');
    await f.writeAsBytes(bytes, flush: true);
    final done = Completer<void>();
    final sub = _player.onPlayerComplete.listen((_) {
      if (!done.isCompleted) done.complete();
    });
    _allDone ??= Completer<void>();
    speaking.value = true;
    _env = null;
    final start = DateTime.now();
    _musicPulse = Timer.periodic(const Duration(milliseconds: 40), (_) {
      final ms = DateTime.now().difference(start).inMilliseconds;
      final beat = (ms * rate / 500) % 1.0; // ~120 bpm, slowed with the song
      level.value = 0.35 + 0.65 * math.pow(1 - beat, 3).toDouble();
    });
    try {
      await _player.setPlaybackRate(rate);
      await _player.play(DeviceFileSource(f.path));
      await done.future;
    } catch (e) {
      debugPrint('Music failed: $e');
    } finally {
      _musicPulse?.cancel();
      await sub.cancel();
      await _player.setPlaybackRate(1.0);
      speaking.value = false;
      level.value = 0;
      final c = _allDone;
      _allDone = null;
      c?.complete();
    }
  }

  Future<void> stop() async {
    _musicPulse?.cancel();
    _queue.clear();
    await _player.stop();
    _playing = false;
    speaking.value = false;
    level.value = 0;
    final c = _allDone;
    _allDone = null;
    c?.complete();
  }

  // --- tiny WAV helpers (16-bit mono PCM, as the hub sends) ---

  static (int rate, int dataStart, int dataLen) _wavInfo(Uint8List wav) {
    final b = ByteData.sublistView(wav);
    var rate = 22050;
    var pos = 12;
    while (pos + 8 <= wav.length) {
      final id = String.fromCharCodes(wav.sublist(pos, pos + 4));
      final size = b.getUint32(pos + 4, Endian.little);
      if (id == 'fmt ') rate = b.getUint32(pos + 12, Endian.little);
      if (id == 'data') return (rate, pos + 8, math.min(size, wav.length - pos - 8));
      pos += 8 + size + (size.isOdd ? 1 : 0);
    }
    return (rate, 44, math.max(0, wav.length - 44));
  }

  static Duration _duration(Uint8List wav) {
    final (rate, _, len) = _wavInfo(wav);
    return Duration(milliseconds: (len / 2 / rate * 1000).round());
  }

  /// Loudness every 40 ms, normalised to 0..1.
  static List<double> _envelope(Uint8List wav) {
    final (rate, start, len) = _wavInfo(wav);
    final b = ByteData.sublistView(wav);
    final step = (rate * _envStepMs / 1000).round();
    final out = <double>[];
    var peak = 1e-6;
    for (var i = 0; i + step * 2 <= len; i += step * 2) {
      var sum = 0.0;
      for (var j = 0; j < step; j++) {
        final s = b.getInt16(start + i + j * 2, Endian.little) / 32768.0;
        sum += s * s;
      }
      final rms = math.sqrt(sum / step);
      out.add(rms);
      peak = math.max(peak, rms);
    }
    return out.map((v) => math.pow(v / peak, 0.6).toDouble()).toList();
  }

  void dispose() {
    _player.dispose();
  }
}

/// Matches "Hey Gipsy" however Whisper decides to spell it.
final RegExp wakePhrase = RegExp(
  r"^\W*(?:(?:hey|hay|hi|okay|ok|a)\W+)?(?:gipsy|gypsy|jipsy|gipsey|gypsie|gipsie|jipsey|gypsey|gipsy's|gypsy's)\b[\W]*",
  caseSensitive: false,
);

/// "there's a kaiju", "kaiju alert", and Whisper's usual misspellings.
final RegExp kaijuPhrase = RegExp(r"\b(kaiju|kai-ju|kai ju|kyju|kaijus)\b", caseSensitive: false);

/// If [heard] starts with the wake phrase, returns whatever came after it
/// ("" if nothing). Returns null if there was no wake phrase.
String? afterWakePhrase(String heard) {
  final m = wakePhrase.firstMatch(heard.trim());
  if (m == null) return null;
  return heard.trim().substring(m.end).trim();
}

/// Splits streamed text into speakable sentences.
class SentenceSplitter {
  final StringBuffer _buf = StringBuffer();
  static final _end = RegExp(r'([.!?]+["”’)]?\s+|\n{2,}|:\s*\n)');

  /// Feed new text; returns any complete sentences.
  List<String> add(String text) {
    _buf.write(text);
    final s = _buf.toString();
    final out = <String>[];
    var last = 0;
    for (final m in _end.allMatches(s)) {
      final piece = s.substring(last, m.end).trim();
      // Avoid tiny fragments like "Dr." by merging short bits forward.
      if (piece.length < 12) continue;
      out.add(piece);
      last = m.end;
    }
    _buf
      ..clear()
      ..write(s.substring(last));
    return out;
  }

  /// Whatever is left at the end of the reply.
  String flush() {
    final s = _buf.toString().trim();
    _buf.clear();
    return s;
  }
}
