import 'dart:async';

import 'package:flutter/foundation.dart';

import 'hub_client.dart';
import 'settings.dart';
import 'visor.dart';
import 'voice.dart';

class ChatLine {
  ChatLine(this.role, this.text, {this.thinking = ''});
  final String role; // user | assistant | system
  String text;
  String thinking;
  bool get isUser => role == 'user';
}

/// Gipsy's behaviour: sleep -> "Hey Gipsy" -> listen -> think -> speak.
class GipsyBrain extends ChangeNotifier {
  GipsyBrain(this.settings) : hub = HubClient(settings);

  final GipsySettings settings;
  final HubClient hub;
  final Ears ears = Ears();
  final Mouth mouth = Mouth();

  GipsyMode mode = GipsyMode.sleeping;
  final List<ChatLine> lines = [];
  HubInfo? hubInfo;
  String status = 'Connecting...';
  bool micAllowed = true;

  bool _wakeLoopRunning = false;
  bool _disposed = false;
  bool _busy = false; // a reply is in progress
  Timer? _sleepTimer;
  int _generation = 0; // bumps on cancel, so old replies stop streaming

  /// The level the visor should react to right now.
  final ValueNotifier<double> visorLevel = ValueNotifier(0);

  Future<void> start() async {
    ears.level.addListener(_syncLevel);
    mouth.level.addListener(_syncLevel);
    await reconnect();
    micAllowed = await ears.hasPermission();
    _maybeStartWakeLoop();
  }

  void _syncLevel() {
    visorLevel.value = mode == GipsyMode.speaking ? mouth.level.value : ears.level.value;
  }

  void _setMode(GipsyMode m) {
    if (_disposed) return;
    mode = m;
    _syncLevel();
    notifyListeners();
  }

  Future<void> reconnect() async {
    status = 'Connecting...';
    notifyListeners();
    if (!settings.isConfigured) {
      status = 'Add your PC address in Settings';
      hubInfo = null;
      notifyListeners();
      return;
    }
    try {
      hubInfo = await hub.connect();
      if (hubInfo == null) {
        status = "Can't reach your PC";
      } else if (!hubInfo!.ollamaUp) {
        status = 'Hub is up, but Ollama is not running';
      } else {
        final via = hubInfo!.url == settings.candidateUrls.first ? 'home Wi-Fi' : 'Tailscale';
        status = 'Online via ${settings.candidateUrls.length > 1 ? via : hubInfo!.url}';
      }
    } catch (e) {
      status = e.toString();
      hubInfo = null;
    }
    notifyListeners();
  }

  String get modelLabel {
    final m = settings.model;
    if (m == 'daily') return 'Daily · ${hubInfo?.dailyModel ?? 'qwen3:8b'}';
    if (m == 'deep') return 'Deep · ${hubInfo?.deepModel ?? 'qwen3:14b'}';
    return m;
  }

  Future<void> setModel(String m) async {
    settings.model = m;
    await settings.save();
    notifyListeners();
  }

  // ---------------------------------------------------------------- wake ----

  void _maybeStartWakeLoop() {
    if (_wakeLoopRunning || !settings.wakeWord || !micAllowed || _disposed) return;
    _wakeLoopRunning = true;
    unawaited(_wakeLoop());
  }

  /// While asleep, keep cutting phrases from the mic and check each one
  /// for "Hey Gipsy". Only phrases with real sound are sent to the PC.
  Future<void> _wakeLoop() async {
    while (!_disposed && settings.wakeWord && mode == GipsyMode.sleeping && micAllowed) {
      String? clip;
      try {
        clip = await ears.listenOnce(
          waitForSpeech: const Duration(seconds: 10),
          maxPhrase: const Duration(seconds: 8),
          endSilence: const Duration(milliseconds: 700),
        );
      } catch (e) {
        debugPrint('Wake mic error: $e');
        micAllowed = false;
        break;
      }
      if (clip == null || mode != GipsyMode.sleeping) continue;
      String heard;
      try {
        heard = await hub.transcribe(clip);
      } catch (_) {
        await Future.delayed(const Duration(seconds: 3));
        continue;
      }
      final rest = afterWakePhrase(heard);
      if (rest == null) continue;
      _wakeLoopRunning = false;
      if (rest.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length >= 2) {
        // "Hey Gipsy, what's the weather" -> answer straight away
        _setMode(GipsyMode.idle);
        await ask(rest);
      } else {
        await wakeAndListen();
      }
      return;
    }
    _wakeLoopRunning = false;
  }

  // ------------------------------------------------------------ actions ----

  /// Tap on the visor, or "Hey Gipsy" on its own: wake and listen.
  Future<void> wakeAndListen() async {
    _sleepTimer?.cancel();
    await mouth.stop();
    await ears.stop();
    if (!micAllowed) {
      micAllowed = await ears.hasPermission();
      if (!micAllowed) {
        _setMode(GipsyMode.idle);
        _system('Microphone access is off. Allow it in Settings to talk to Gipsy.');
        _scheduleSleep();
        return;
      }
    }
    _setMode(GipsyMode.listening);
    final clip = await ears.listenOnce(waitForSpeech: const Duration(seconds: 7));
    if (clip == null) {
      _setMode(GipsyMode.idle);
      _scheduleSleep(seconds: 8);
      return;
    }
    _setMode(GipsyMode.thinking);
    String heard;
    try {
      heard = await hub.transcribe(clip);
    } catch (e) {
      _system(e.toString());
      _setMode(GipsyMode.idle);
      _scheduleSleep();
      return;
    }
    heard = afterWakePhrase(heard) ?? heard;
    if (heard.isEmpty) {
      _setMode(GipsyMode.idle);
      _scheduleSleep(seconds: 8);
      return;
    }
    await ask(heard);
  }

  /// Send a message (typed or spoken) and handle the reply.
  Future<void> ask(String text) async {
    text = text.trim();
    if (text.isEmpty) return;
    if (_busy) await cancel();
    _sleepTimer?.cancel();
    await ears.stop();
    final gen = ++_generation;
    _busy = true;

    lines.add(ChatLine('user', text));
    final reply = ChatLine('assistant', '');
    lines.add(reply);
    _setMode(GipsyMode.thinking);

    final history = lines
        .where((l) => l.role != 'system' && l != reply && l.text.isNotEmpty)
        .map((l) => {'role': l.role, 'content': l.text})
        .toList();

    final splitter = SentenceSplitter();
    final speak = settings.voiceReplies;
    var gotError = false;

    // Keep sentence order: chain TTS requests one after another.
    var ttsChain = Future<void>.value();
    void sayInOrder(String s) {
      ttsChain = ttsChain.then((_) async {
        if (gen != _generation || !speak) return;
        try {
          final wav = await hub.speak(s);
          if (gen != _generation) return;
          mouth.enqueue(wav);
          if (mode != GipsyMode.speaking) _setMode(GipsyMode.speaking);
        } catch (e) {
          debugPrint('TTS: $e');
        }
      });
    }

    try {
      await for (final ev in hub.chat(history, model: settings.model)) {
        if (gen != _generation) return;
        switch (ev.type) {
          case 'thinking':
            reply.thinking += ev.text;
            notifyListeners();
          case 'token':
            reply.text += ev.text;
            // strip any <think> blocks some models put inline
            reply.text = reply.text.replaceAll(RegExp(r'<think>[\s\S]*?</think>\s*'), '');
            for (final s in splitter.add(ev.text)) {
              sayInOrder(s);
            }
            notifyListeners();
          case 'error':
            gotError = true;
            reply.text = ev.text;
            notifyListeners();
          default:
            break;
        }
      }
    } catch (e) {
      gotError = true;
      reply.text = e.toString();
      notifyListeners();
    }
    if (gen != _generation) return;

    if (!gotError) sayInOrder(splitter.flush());
    if (reply.text.isEmpty) reply.text = '(no reply)';
    notifyListeners();

    await ttsChain;
    if (gen != _generation) return;
    if (mode == GipsyMode.thinking && !mouth.speaking.value) _setMode(GipsyMode.idle);
    await mouth.finished;
    if (gen != _generation) return;
    _busy = false;
    _setMode(GipsyMode.idle);

    if (!gotError && speak && settings.conversationMode && micAllowed) {
      // Follow-up without the wake word. Goes back to sleep if you're quiet.
      await Future.delayed(const Duration(milliseconds: 250));
      if (gen == _generation && mode == GipsyMode.idle) await wakeAndListen();
    } else {
      _scheduleSleep();
    }
  }

  /// Stop talking/thinking right now.
  Future<void> cancel() async {
    _generation++;
    _busy = false;
    await mouth.stop();
    await ears.stop();
    _setMode(GipsyMode.idle);
    _scheduleSleep();
  }

  void sleepNow() {
    _sleepTimer?.cancel();
    _generation++;
    _busy = false;
    mouth.stop();
    ears.stop();
    _setMode(GipsyMode.sleeping);
    Future.delayed(const Duration(milliseconds: 300), _maybeStartWakeLoop);
  }

  void _scheduleSleep({int seconds = 20}) {
    _sleepTimer?.cancel();
    _sleepTimer = Timer(Duration(seconds: seconds), () {
      if (mode == GipsyMode.idle && !_busy) sleepNow();
    });
  }

  void _system(String text) {
    lines.add(ChatLine('system', text));
    notifyListeners();
  }

  void clearChat() {
    lines.clear();
    notifyListeners();
  }

  /// Call after Settings change.
  Future<void> settingsChanged() async {
    await reconnect();
    if (!settings.wakeWord) {
      if (mode == GipsyMode.sleeping) await ears.stop();
    } else if (mode == GipsyMode.sleeping) {
      _maybeStartWakeLoop();
    }
  }

  /// App went to background: release the mic.
  Future<void> pause() async {
    _generation++;
    await ears.stop();
    await mouth.stop();
    _wakeLoopRunning = false;
    _setMode(GipsyMode.sleeping);
  }

  void resume() {
    _maybeStartWakeLoop();
    reconnect();
  }

  @override
  void dispose() {
    _disposed = true;
    _sleepTimer?.cancel();
    ears.dispose();
    mouth.dispose();
    super.dispose();
  }
}
