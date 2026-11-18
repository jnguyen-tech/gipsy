import 'package:flutter/material.dart';

import 'brain.dart';
import 'settings_page.dart';
import 'theme.dart';
import 'visor.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.brain});
  final GipsyBrain brain;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _input = TextEditingController();
  final _scroll = ScrollController();

  GipsyBrain get brain => widget.brain;

  @override
  void initState() {
    super.initState();
    brain.addListener(_onChange);
  }

  @override
  void dispose() {
    brain.removeListener(_onChange);
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _onChange() {
    if (!mounted) return;
    setState(() {});
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  void _send() {
    final t = _input.text;
    _input.clear();
    brain.ask(t);
  }

  String get _modeLabel => switch (brain.mode) {
        GipsyMode.sleeping => brain.settings.wakeWord && brain.micAllowed
            ? 'Sleeping · say "Hey Gipsy" or tap'
            : 'Sleeping · tap to wake',
        GipsyMode.idle => 'Awake',
        GipsyMode.listening => 'Listening...',
        GipsyMode.thinking => 'Thinking...',
        GipsyMode.speaking => 'Speaking',
      };

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width > 820;
    final head = _HeadPanel(brain: brain, modeLabel: _modeLabel);
    final chat = _ChatPanel(brain: brain, scroll: _scroll, input: _input, onSend: _send);

    return Scaffold(
      appBar: AppBar(
        title: Row(mainAxisSize: MainAxisSize.min, children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.asset('assets/brand/armored_g.png', width: 26, height: 26),
          ),
          const SizedBox(width: 10),
          const Text('GIPSY', style: TextStyle(letterSpacing: 6, fontWeight: FontWeight.w700)),
        ]),
        leading: _ModelMenu(brain: brain),
        leadingWidth: 64,
        actions: [
          IconButton(
            tooltip: 'Go to sleep',
            icon: const Icon(Icons.bedtime_outlined),
            onPressed: brain.sleepNow,
          ),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.tune),
            onPressed: () async {
              await Navigator.of(context).push(MaterialPageRoute(builder: (_) => SettingsPage(brain: brain)));
              await brain.settingsChanged();
            },
          ),
        ],
      ),
      body: SafeArea(
        child: wide
            ? Row(children: [
                SizedBox(width: 380, child: head),
                const VerticalDivider(width: 1, color: GipsyColors.navy),
                Expanded(child: chat),
              ])
            : Column(children: [head, Expanded(child: chat)]),
      ),
    );
  }
}

class _HeadPanel extends StatelessWidget {
  const _HeadPanel({required this.brain, required this.modeLabel});
  final GipsyBrain brain;
  final String modeLabel;

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final visorSize = size.width > 820 ? 300.0 : (size.height < 700 ? 170.0 : 220.0);
    final online = brain.hubInfo?.ollamaUp == true;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Column(mainAxisSize: MainAxisSize.min, mainAxisAlignment: MainAxisAlignment.center, children: [
        GestureDetector(
          onTap: () {
            if (brain.mode == GipsyMode.speaking || brain.mode == GipsyMode.thinking) {
              brain.cancel();
            } else {
              brain.wakeAndListen();
            }
          },
          child: Visor(mode: brain.mode, level: brain.visorLevel, size: visorSize),
        ),
        const SizedBox(height: 10),
        Row(mainAxisSize: MainAxisSize.min, children: [
          ReactorSpinner(size: 22, active: brain.mode == GipsyMode.thinking),
          const SizedBox(width: 8),
          Text(modeLabel,
              style: TextStyle(
                  color: brain.mode == GipsyMode.sleeping ? GipsyColors.steel : GipsyColors.amber,
                  fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 4),
        InkWell(
          onTap: brain.reconnect,
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.circle, size: 9, color: online ? Colors.greenAccent : Colors.redAccent),
            const SizedBox(width: 6),
            Flexible(
              child: Text(brain.status,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: GipsyColors.steel, fontSize: 12)),
            ),
          ]),
        ),
      ]),
    );
  }
}

class _ModelMenu extends StatelessWidget {
  const _ModelMenu({required this.brain});
  final GipsyBrain brain;

  @override
  Widget build(BuildContext context) {
    final current = brain.settings.model;
    final extra = (brain.hubInfo?.models ?? [])
        .where((m) => m != brain.hubInfo?.dailyModel && m != brain.hubInfo?.deepModel)
        .where((m) => !m.contains('embed'))
        .toList();
    return PopupMenuButton<String>(
      tooltip: 'Choose brain',
      initialValue: current,
      onSelected: brain.setModel,
      icon: Icon(current == 'deep' ? Icons.psychology : Icons.bolt,
          color: current == 'deep' ? GipsyColors.amberHot : GipsyColors.amber),
      itemBuilder: (_) => [
        PopupMenuItem(
          value: 'daily',
          child: ListTile(
            leading: const Icon(Icons.bolt),
            title: const Text('Daily'),
            subtitle: Text('${brain.hubInfo?.dailyModel ?? 'qwen3:8b'} · fast'),
          ),
        ),
        PopupMenuItem(
          value: 'deep',
          child: ListTile(
            leading: const Icon(Icons.psychology),
            title: const Text('Deep'),
            subtitle: Text('${brain.hubInfo?.deepModel ?? 'qwen3:14b'} · smarter, slower'),
          ),
        ),
        if (extra.isNotEmpty) const PopupMenuDivider(),
        for (final m in extra) PopupMenuItem(value: m, child: Text(m)),
      ],
    );
  }
}

class _ChatPanel extends StatelessWidget {
  const _ChatPanel({required this.brain, required this.scroll, required this.input, required this.onSend});
  final GipsyBrain brain;
  final ScrollController scroll;
  final TextEditingController input;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(children: [
          Text(brain.modelLabel, style: const TextStyle(color: GipsyColors.steel, fontSize: 12)),
          const Spacer(),
          if (brain.lines.isNotEmpty)
            TextButton(onPressed: brain.clearChat, child: const Text('New chat')),
        ]),
      ),
      Expanded(
        child: brain.lines.isEmpty
            ? const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('Say "Hey Gipsy", tap the visor, or type below.',
                      textAlign: TextAlign.center, style: TextStyle(color: GipsyColors.steel)),
                ),
              )
            : ListView.builder(
                controller: scroll,
                padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
                itemCount: brain.lines.length,
                itemBuilder: (_, i) => _Bubble(line: brain.lines[i], showThinking: brain.settings.showThinking),
              ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: input,
              minLines: 1,
              maxLines: 5,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => onSend(),
              decoration: const InputDecoration(hintText: 'Message Gipsy'),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            tooltip: 'Talk',
            onPressed: brain.mode == GipsyMode.listening ? brain.cancel : brain.wakeAndListen,
            icon: Icon(brain.mode == GipsyMode.listening ? Icons.stop : Icons.mic),
          ),
          const SizedBox(width: 4),
          IconButton.filledTonal(tooltip: 'Send', onPressed: onSend, icon: const Icon(Icons.arrow_upward)),
        ]),
      ),
    ]);
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.line, required this.showThinking});
  final ChatLine line;
  final bool showThinking;

  @override
  Widget build(BuildContext context) {
    if (line.role == 'system') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Text(line.text,
            textAlign: TextAlign.center, style: const TextStyle(color: Colors.orangeAccent, fontSize: 12)),
      );
    }
    final user = line.isUser;
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: user ? GipsyColors.amberDeep.withValues(alpha: 0.85) : GipsyColors.navy,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(16),
              topRight: const Radius.circular(16),
              bottomLeft: Radius.circular(user ? 16 : 4),
              bottomRight: Radius.circular(user ? 4 : 16),
            ),
            border: user ? null : Border.all(color: GipsyColors.navyPlate),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (!user && showThinking && line.thinking.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(line.thinking.trim(),
                    style: const TextStyle(color: GipsyColors.steel, fontSize: 12, fontStyle: FontStyle.italic)),
              ),
            if (!user && line.text.isEmpty)
              const Row(mainAxisSize: MainAxisSize.min, children: [
                ReactorSpinner(size: 18),
                SizedBox(width: 8),
                Text('...', style: TextStyle(color: GipsyColors.steel)),
              ])
            else
              SelectableText(line.text, style: const TextStyle(height: 1.35)),
          ]),
        ),
      ),
    );
  }
}
