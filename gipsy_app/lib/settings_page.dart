import 'package:flutter/material.dart';

import 'brain.dart';
import 'theme.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.brain});
  final GipsyBrain brain;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final s = widget.brain.settings;
  late final _home = TextEditingController(text: s.homeUrl);
  late final _ts = TextEditingController(text: s.tailscaleUrl);
  late final _key = TextEditingController(text: s.apiKey);
  String? _test;

  Future<void> _save() async {
    s
      ..homeUrl = _home.text
      ..tailscaleUrl = _ts.text
      ..apiKey = _key.text;
    await s.save();
  }

  Future<void> _testConnection() async {
    await _save();
    setState(() => _test = 'Testing...');
    await widget.brain.reconnect();
    setState(() => _test = widget.brain.status);
  }

  @override
  void dispose() {
    _save();
    _home.dispose();
    _ts.dispose();
    _key.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GipsyBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(title: const TrackedLabel('Settings', color: GipsyColors.steelBright, size: 14)),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const _Header('Your PC'),
            TextField(
              controller: _home,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: 'Home Wi-Fi address', hintText: 'http://192.168.1.50:8765'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _ts,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'Tailscale address (away from home)',
                hintText: 'http://100.x.y.z:8765',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _key,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Hub key (optional)'),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                FilledButton.icon(
                  onPressed: _testConnection,
                  icon: const Icon(Icons.wifi_tethering),
                  label: const Text('Test'),
                ),
                const SizedBox(width: 12),
                if (_test != null)
                  Expanded(
                    child: Text(_test!, style: const TextStyle(color: GipsyColors.steel)),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'On the PC itself you can use http://127.0.0.1:8765. The hub window shows the exact Wi-Fi address when it starts.',
              style: TextStyle(color: GipsyColors.steel, fontSize: 12),
            ),
            const _Header('Voice'),
            SwitchListTile(
              title: const Text('Speak replies out loud'),
              subtitle: const Text('Deep British voice from your PC'),
              value: s.voiceReplies,
              onChanged: (v) => setState(() => s.voiceReplies = v),
            ),
            SwitchListTile(
              title: const Text('Listen for "Hey Gipsy"'),
              subtitle: const Text('Only while the app is open'),
              value: s.wakeWord,
              onChanged: (v) => setState(() => s.wakeWord = v),
            ),
            SwitchListTile(
              title: const Text('Conversation mode'),
              subtitle: const Text('Keep listening for a follow-up after Gipsy answers'),
              value: s.conversationMode,
              onChanged: (v) => setState(() => s.conversationMode = v),
            ),
            const _Header('Brain'),
            SwitchListTile(
              title: const Text('Show thinking'),
              subtitle: const Text("Show qwen3's reasoning in Deep mode"),
              value: s.showThinking,
              onChanged: (v) => setState(() => s.showThinking = v),
            ),
            const SizedBox(height: 24),
            Center(child: Image.asset('assets/brand/armored_g.png', width: 56, height: 56)),
            const SizedBox(height: 6),
            const Center(
              child: Text(
                'Gipsy 1.0 · runs 100% on your own PC',
                style: TextStyle(color: GipsyColors.steel, fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 20, bottom: 10),
    child: Text(
      text.toUpperCase(),
      style: const TextStyle(color: GipsyColors.amber, letterSpacing: 2, fontWeight: FontWeight.w700, fontSize: 12),
    ),
  );
}
