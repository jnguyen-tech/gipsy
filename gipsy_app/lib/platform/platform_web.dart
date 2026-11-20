import 'dart:async';
import 'dart:js_interop';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:web/web.dart' as web;

// In the browser the recorder hands back a "blob:" link to the WAV it made,
// instead of a file path. These helpers read and free those links.

/// The browser recorder ignores the path, so any name will do.
Future<String> newClipPath() async => 'gipsy.wav';

/// The bytes of a recorded phrase (fetched from its blob: link).
Future<Uint8List> readClip(String clip) async {
  final res = await web.window.fetch(clip.toJS).toDart;
  final buf = await res.arrayBuffer().toDart;
  return buf.toDart.asUint8List();
}

/// Frees a recorded phrase once it has been used.
Future<void> deleteClip(String clip) async {
  if (clip.startsWith('blob:')) web.URL.revokeObjectURL(clip);
}

web.AudioContext? _ctx;
web.AudioContext get _context => _ctx ??= web.AudioContext();

/// Safari only lets a page make sound after the user taps something. Call
/// this from a tap: it wakes the sound system and plays a silent blip, and
/// after that Gipsy may speak whenever it wants.
Future<void> unlockAudio() async {
  final ctx = _context;
  try {
    await ctx.resume().toDart;
  } catch (_) {}
  final src = ctx.createBufferSource()..buffer = ctx.createBuffer(1, 1, 22050);
  src.connect(ctx.destination);
  src.start();
}

/// Why the mic can't work here, or null if it can.
///
/// Browsers only give web pages the mic on a secure (https://) address.
/// http://192.168.x.x works for typing, but not for talking.
String? micProblem() {
  if (!web.window.isSecureContext) {
    return 'To talk to Gipsy here, open the secure https:// address (Tailscale). '
        'Typing works on this address, but browsers block the mic on plain http://.';
  }
  return null;
}

/// Plays one sound at a time with the Web Audio API.
///
/// Web Audio is used instead of an <audio> tag because once it has been
/// unlocked by a tap, Safari lets it play replies that arrive later.
class ClipPlayer {
  final StreamController<void> _complete = StreamController<void>.broadcast();
  final StreamController<Duration> _position = StreamController<Duration>.broadcast();
  web.AudioBufferSourceNode? _src;
  web.GainNode? _gain;
  Timer? _tick;
  int _token = 0; // bumps on stop, so an old sound can't report "finished"
  double _volume = 1.0;

  Stream<void> get onComplete => _complete.stream;
  Stream<Duration> get onPosition => _position.stream;

  Future<void> play(Uint8List bytes, String ext, {Duration? position, double rate = 1.0}) async {
    await stop();
    final token = ++_token;
    final ctx = _context;
    if (ctx.state == 'suspended') {
      try {
        await ctx.resume().toDart;
      } catch (_) {}
    }
    // decodeAudioData takes ownership of the bytes, so give it a copy.
    final copy = Uint8List.fromList(bytes);
    final audio = await ctx.decodeAudioData(copy.buffer.toJS).toDart;
    if (token != _token) return; // stopped while decoding
    final gain = _gain = ctx.createGain();
    gain.gain.value = _volume;
    gain.connect(ctx.destination);
    final src = _src = ctx.createBufferSource();
    src.buffer = audio;
    src.playbackRate.value = rate;
    src.connect(gain);
    final offset = math.min((position?.inMilliseconds ?? 0) / 1000.0, audio.duration);
    final startedAt = ctx.currentTime;
    src.onended = ((web.Event _) {
      if (token != _token) return;
      _tick?.cancel();
      _complete.add(null);
    }).toJS;
    src.start(0, offset);
    _tick = Timer.periodic(const Duration(milliseconds: 40), (_) {
      final t = (ctx.currentTime - startedAt) * rate + offset;
      _position.add(Duration(milliseconds: (t * 1000).round()));
    });
  }

  Future<void> setVolume(double v) async {
    _volume = v;
    _gain?.gain.value = v;
  }

  Future<void> stop() async {
    _token++;
    _tick?.cancel();
    final src = _src;
    _src = null;
    if (src != null) {
      try {
        src.stop();
      } catch (_) {}
      src.disconnect();
    }
    _gain?.disconnect();
    _gain = null;
  }

  void dispose() {
    stop();
    _complete.close();
    _position.close();
  }
}
