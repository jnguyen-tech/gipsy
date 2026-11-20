import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'platform/platform.dart';
import 'settings.dart';

/// One event from the hub's /api/chat stream.
class ChatEvent {
  ChatEvent(this.type, this.text, {this.model});
  final String type; // start | thinking | token | done | error
  final String text;
  final String? model;
}

class HubInfo {
  HubInfo(this.url, this.json);
  final String url;
  final Map<String, dynamic> json;
  bool get ollamaUp => json['ollama'] == true;
  List<String> get models => (json['models'] as List? ?? []).cast<String>();
  String get dailyModel => json['daily_model'] as String? ?? 'qwen3:8b';
  String get deepModel => json['deep_model'] as String? ?? 'qwen3:14b';

  /// Things that failed to load on the PC, e.g. {"hearing": "..."}.
  Map<String, String> get problems =>
      (json['problems'] as Map? ?? {}).map((k, v) => MapEntry(k.toString(), v.toString()));
}

/// The hub's reason for an error ({"detail": "..."}), or null.
String? hubDetail(http.Response r) {
  try {
    final d = (jsonDecode(r.body) as Map?)?['detail'];
    return d is String && d.isNotEmpty ? d : null;
  } catch (_) {
    return null;
  }
}

/// Talks to Gipsy Hub on the PC. Tries home Wi-Fi first, then Tailscale.
class HubClient {
  HubClient(this.settings);
  final GipsySettings settings;
  final http.Client _http = http.Client();

  String? _activeUrl;
  String? get activeUrl => _activeUrl;

  Map<String, String> get _headers => {if (settings.apiKey.trim().isNotEmpty) 'X-Gipsy-Key': settings.apiKey.trim()};

  /// Finds a hub address that answers. Returns null if none do.
  Future<HubInfo?> connect() async {
    for (final url in settings.candidateUrls) {
      try {
        final r = await _http.get(Uri.parse('$url/api/health'), headers: _headers).timeout(const Duration(seconds: 3));
        if (r.statusCode == 200) {
          _activeUrl = url;
          return HubInfo(url, jsonDecode(r.body) as Map<String, dynamic>);
        }
        if (r.statusCode == 401) {
          throw HubException('The hub rejected the key. Check the key in Settings.');
        }
      } on HubException {
        rethrow;
      } catch (_) {
        // try the next address
      }
    }
    _activeUrl = null;
    return null;
  }

  Future<String> _base() async {
    if (_activeUrl != null) return _activeUrl!;
    final info = await connect();
    if (info == null) {
      throw HubException("I can't reach Gipsy Hub. Is the PC on and the hub running?");
    }
    return info.url;
  }

  /// Streams a reply. [history] is the whole conversation so far.
  Stream<ChatEvent> chat(List<Map<String, String>> history, {required String model}) async* {
    final base = await _base();
    final req = http.Request('POST', Uri.parse('$base/api/chat'))
      ..headers.addAll({..._headers, 'Content-Type': 'application/json'})
      ..body = jsonEncode({'messages': history, 'model': model});
    final http.StreamedResponse res;
    try {
      res = await _http.send(req).timeout(const Duration(seconds: 15));
    } catch (e) {
      _activeUrl = null;
      yield ChatEvent('error', "Lost the connection to the hub. ($e)");
      return;
    }
    if (res.statusCode != 200) {
      yield ChatEvent('error', 'Hub error ${res.statusCode}');
      return;
    }
    await for (final line in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.trim().isEmpty) continue;
      final j = jsonDecode(line) as Map<String, dynamic>;
      yield ChatEvent(j['type'] as String, (j['text'] as String?) ?? '', model: j['model'] as String?);
    }
  }

  /// Text -> WAV bytes in Gipsy's voice.
  /// [preset] tries another voice (a preview) without switching to it.
  Future<Uint8List> speak(String text, {String? preset}) async {
    final base = await _base();
    final r = await _http
        .post(
          Uri.parse('$base/api/tts'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'text': text, 'preset': ?preset}),
        )
        .timeout(const Duration(seconds: 60));
    if (r.statusCode != 200) throw HubException(hubDetail(r) ?? 'Voice failed (${r.statusCode})');
    return r.bodyBytes;
  }

  /// Every voice the hub has: [{id, label, about, available, why, current}].
  Future<List<Map<String, dynamic>>> voices() async =>
      ((await voiceInfo())['voices'] as List).cast<Map<String, dynamic>>();

  /// {current, pace, voices: [...]}
  Future<Map<String, dynamic>> voiceInfo() async {
    final base = await _base();
    final r = await _http.get(Uri.parse('$base/api/voices'), headers: _headers).timeout(const Duration(seconds: 10));
    if (r.statusCode == 404) throw HubException('Update Gipsy Hub on the PC to pick voices from the app.');
    if (r.statusCode != 200) throw HubException(hubDetail(r) ?? 'Couldn\'t load voices (${r.statusCode})');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Talking speed: 1.0 normal, 1.25 = 25% faster. Saved on the PC.
  Future<double> setPace(double pace) async {
    final base = await _base();
    final r = await _http
        .post(
          Uri.parse('$base/api/voice/pace'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'pace': pace}),
        )
        .timeout(const Duration(seconds: 10));
    if (r.statusCode == 404) throw HubException('Update Gipsy Hub on the PC to change the speed from the app.');
    if (r.statusCode != 200) throw HubException(hubDetail(r) ?? 'Couldn\'t change the speed (${r.statusCode})');
    return ((jsonDecode(r.body) as Map)['pace'] as num).toDouble();
  }

  /// Makes [preset] Gipsy's voice on every device (saved on the PC).
  Future<void> setVoice(String preset) async {
    final base = await _base();
    final r = await _http
        .post(
          Uri.parse('$base/api/voice'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'preset': preset}),
        )
        .timeout(const Duration(seconds: 10));
    if (r.statusCode != 200) throw HubException(hubDetail(r) ?? 'Couldn\'t change the voice (${r.statusCode})');
  }

  /// Recorded WAV file -> text.
  Future<String> transcribe(String wavPath) async {
    final base = await _base();
    final req = http.MultipartRequest('POST', Uri.parse('$base/api/stt'))
      ..headers.addAll(_headers)
      ..files.add(http.MultipartFile.fromBytes('audio', await readClip(wavPath), filename: 'clip.wav'));
    // The clip has been read, so it can go (temp file, or blob: link in a browser).
    unawaited(deleteClip(wavPath));
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 60)));
    if (res.statusCode != 200) throw HubException('Hearing failed: ${hubDetail(res) ?? res.statusCode}');
    return ((jsonDecode(res.body) as Map)['text'] as String? ?? '').trim();
  }

  /// Kaiju alert settings: {line, has_song, song_ext, rate}.
  Future<Map<String, dynamic>> kaijuInfo() async {
    final base = await _base();
    final r = await _http.get(Uri.parse('$base/api/kaiju'), headers: _headers).timeout(const Duration(seconds: 5));
    if (r.statusCode != 200) throw HubException('Kaiju alert failed (${r.statusCode})');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  /// Downloads the battle song chosen in the hub's config.json.
  Future<Uint8List> kaijuSong() async {
    final base = await _base();
    final r = await _http
        .get(Uri.parse('$base/api/kaiju/song'), headers: _headers)
        .timeout(const Duration(seconds: 60));
    if (r.statusCode != 200) throw HubException('No battle song (${r.statusCode})');
    return r.bodyBytes;
  }

  /// This week's agenda: calendars, to-do list and market events, by day.
  Future<Map<String, dynamic>> week({int days = 7}) async {
    final base = await _base();
    final r = await _http
        .get(Uri.parse('$base/api/week?days=$days'), headers: _headers)
        .timeout(const Duration(seconds: 30));
    if (r.statusCode != 200) throw HubException('Couldn\'t load your week (${r.statusCode})');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> addTask(String title, {String due = '', String kind = 'task'}) async {
    final base = await _base();
    final r = await _http
        .post(
          Uri.parse('$base/api/tasks'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'title': title, 'due': due, 'kind': kind}),
        )
        .timeout(const Duration(seconds: 10));
    if (r.statusCode != 200) {
      final detail = (jsonDecode(r.body) as Map?)?['detail'];
      throw HubException(detail is String ? detail : 'Couldn\'t add the task (${r.statusCode})');
    }
  }

  Future<void> completeTask(String id) async {
    final base = await _base();
    await _http.post(Uri.parse('$base/api/tasks/$id/done'), headers: _headers).timeout(const Duration(seconds: 10));
  }

  Future<void> deleteTask(String id) async {
    final base = await _base();
    await _http.delete(Uri.parse('$base/api/tasks/$id'), headers: _headers).timeout(const Duration(seconds: 10));
  }

  /// Calendars the hub reads (links come back masked).
  Future<List<Map<String, dynamic>>> calendars() async {
    final base = await _base();
    final r = await _http.get(Uri.parse('$base/api/calendars'), headers: _headers).timeout(const Duration(seconds: 10));
    if (r.statusCode == 404) throw HubException('Update Gipsy Hub on the PC to link calendars from the app.');
    if (r.statusCode != 200) throw HubException('Couldn\'t load calendars (${r.statusCode})');
    return (jsonDecode(r.body) as List).cast<Map<String, dynamic>>();
  }

  /// Links an iCal feed. Returns the saved calendar plus {ok, error} from a test download.
  Future<Map<String, dynamic>> linkCalendar(String name, String url, String kind) async {
    final base = await _base();
    final r = await _http
        .post(
          Uri.parse('$base/api/calendars'),
          headers: {..._headers, 'Content-Type': 'application/json'},
          body: jsonEncode({'name': name, 'url': url, 'kind': kind}),
        )
        .timeout(const Duration(seconds: 40));
    if (r.statusCode != 200) {
      final detail = (jsonDecode(r.body) as Map?)?['detail'];
      throw HubException(detail is String ? detail : 'Couldn\'t link the calendar (${r.statusCode})');
    }
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> unlinkCalendar(String id) async {
    final base = await _base();
    await _http.delete(Uri.parse('$base/api/calendars/$id'), headers: _headers).timeout(const Duration(seconds: 10));
  }
}

class HubException implements Exception {
  HubException(this.message);
  final String message;
  @override
  String toString() => message;
}
