import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

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
}

/// Talks to Gipsy Hub on the PC. Tries home Wi-Fi first, then Tailscale.
class HubClient {
  HubClient(this.settings);
  final GipsySettings settings;
  final http.Client _http = http.Client();

  String? _activeUrl;
  String? get activeUrl => _activeUrl;

  Map<String, String> get _headers => {
        if (settings.apiKey.trim().isNotEmpty) 'X-Gipsy-Key': settings.apiKey.trim(),
      };

  /// Finds a hub address that answers. Returns null if none do.
  Future<HubInfo?> connect() async {
    for (final url in settings.candidateUrls) {
      try {
        final r = await _http
            .get(Uri.parse('$url/api/health'), headers: _headers)
            .timeout(const Duration(seconds: 3));
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
    await for (final line
        in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.trim().isEmpty) continue;
      final j = jsonDecode(line) as Map<String, dynamic>;
      yield ChatEvent(j['type'] as String, (j['text'] as String?) ?? '',
          model: j['model'] as String?);
    }
  }

  /// Text -> WAV bytes in Gipsy's voice.
  Future<Uint8List> speak(String text) async {
    final base = await _base();
    final r = await _http
        .post(Uri.parse('$base/api/tts'),
            headers: {..._headers, 'Content-Type': 'application/json'},
            body: jsonEncode({'text': text}))
        .timeout(const Duration(seconds: 60));
    if (r.statusCode != 200) throw HubException('Voice failed (${r.statusCode})');
    return r.bodyBytes;
  }

  /// Recorded WAV file -> text.
  Future<String> transcribe(String wavPath) async {
    final base = await _base();
    final req = http.MultipartRequest('POST', Uri.parse('$base/api/stt'))
      ..headers.addAll(_headers)
      ..files.add(await http.MultipartFile.fromPath('audio', wavPath, filename: 'clip.wav'));
    final res = await http.Response.fromStream(
        await _http.send(req).timeout(const Duration(seconds: 60)));
    if (res.statusCode != 200) throw HubException('Hearing failed (${res.statusCode})');
    return ((jsonDecode(res.body) as Map)['text'] as String? ?? '').trim();
  }
}

class HubException implements Exception {
  HubException(this.message);
  final String message;
  @override
  String toString() => message;
}
