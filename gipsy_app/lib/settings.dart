import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Everything the user can change on the Settings screen, saved on device.
class GipsySettings extends ChangeNotifier {
  /// Hub address on home Wi-Fi, e.g. http://192.168.1.50:8765
  String homeUrl = '';

  /// Hub address over Tailscale, e.g. http://100.101.102.103:8765
  String tailscaleUrl = '';

  /// Optional shared secret (matches api_key in the hub's config.json).
  String apiKey = '';

  /// "daily", "deep", or an exact Ollama model tag.
  String model = 'daily';

  /// Speak replies out loud.
  bool voiceReplies = true;

  /// Listen for "Hey Gipsy" while the app is open.
  bool wakeWord = true;

  /// After Gipsy answers, keep listening for a follow-up without the wake word.
  bool conversationMode = true;

  /// Show qwen3's reasoning text in the chat while it thinks.
  bool showThinking = false;

  static const _k = 'gipsy.';

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    homeUrl = p.getString('${_k}homeUrl') ?? homeUrl;
    tailscaleUrl = p.getString('${_k}tailscaleUrl') ?? tailscaleUrl;
    apiKey = p.getString('${_k}apiKey') ?? apiKey;
    model = p.getString('${_k}model') ?? model;
    voiceReplies = p.getBool('${_k}voiceReplies') ?? voiceReplies;
    wakeWord = p.getBool('${_k}wakeWord') ?? wakeWord;
    conversationMode = p.getBool('${_k}conversationMode') ?? conversationMode;
    showThinking = p.getBool('${_k}showThinking') ?? showThinking;
    notifyListeners();
  }

  Future<void> save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('${_k}homeUrl', homeUrl.trim());
    await p.setString('${_k}tailscaleUrl', tailscaleUrl.trim());
    await p.setString('${_k}apiKey', apiKey.trim());
    await p.setString('${_k}model', model);
    await p.setBool('${_k}voiceReplies', voiceReplies);
    await p.setBool('${_k}wakeWord', wakeWord);
    await p.setBool('${_k}conversationMode', conversationMode);
    await p.setBool('${_k}showThinking', showThinking);
    notifyListeners();
  }

  bool get isConfigured => candidateUrls.isNotEmpty;

  /// In the web version: the address the page was opened from. The hub
  /// serves the web app itself, so that address IS the hub. Null in the
  /// native apps.
  static String? get pageOrigin {
    if (!kIsWeb) return null;
    final u = Uri.base;
    return (u.scheme == 'http' || u.scheme == 'https') ? u.origin : null;
  }

  /// Addresses to try, in order. Home Wi-Fi first because it is fastest.
  /// The web version tries the page's own address first.
  List<String> get candidateUrls {
    final origin = pageOrigin;
    final urls = [?origin, homeUrl, tailscaleUrl]
        .map((u) => u.trim())
        .where((u) => u.isNotEmpty)
        .map((u) => u.startsWith('http') ? u : 'http://$u')
        .map((u) => u.endsWith('/') ? u.substring(0, u.length - 1) : u)
        // A secure (https) page may not call plain http addresses.
        .where((u) => origin == null || !origin.startsWith('https:') || u.startsWith('https:'))
        .toList();
    return urls.toSet().toList();
  }

  /// A short name for [url] in the status line.
  String describe(String url) {
    if (url == pageOrigin) return 'this address';
    final home = homeUrl.trim();
    if (home.isNotEmpty && url.contains(home.replaceFirst(RegExp(r'^https?://'), ''))) return 'home Wi-Fi';
    return 'Tailscale';
  }
}
