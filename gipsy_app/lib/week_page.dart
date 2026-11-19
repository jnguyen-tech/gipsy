import 'package:flutter/material.dart';

import 'calendars_sheet.dart';
import 'hub_client.dart';
import 'theme.dart';

/// "This week": school work, appointments, your to-do list and market events,
/// one armour panel per day. Pull down to refresh.
class WeekPage extends StatefulWidget {
  const WeekPage({super.key, required this.hub});
  final HubClient hub;

  @override
  State<WeekPage> createState() => _WeekPageState();
}

class _WeekPageState extends State<WeekPage> {
  Map<String, dynamic>? _week;
  String? _error;
  bool _loading = true;
  final _newTask = TextEditingController();
  final _newDue = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _newTask.dispose();
    _newDue.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final w = await widget.hub.week();
      setState(() {
        _week = w;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _add() async {
    final title = _newTask.text.trim();
    if (title.isEmpty) return;
    try {
      await widget.hub.addTask(title, due: _newDue.text.trim());
      _newTask.clear();
      _newDue.clear();
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _done(String id) async {
    await widget.hub.completeTask(id);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final w = _week;
    return GipsyBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          title: const TrackedLabel('This week', color: GipsyColors.steelBright, size: 14),
          actions: [
            IconButton(
              tooltip: 'Calendars',
              icon: const Icon(Icons.link),
              onPressed: () async {
                await showCalendarsSheet(context, widget.hub);
                await _load();
              },
            ),
            IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh)),
          ],
        ),
        body: RefreshIndicator(
          onRefresh: _load,
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 4, 14, 24),
                children: [
                  _addRow(),
                  const SizedBox(height: 14),
                  if (_loading && w == null)
                    const Padding(
                      padding: EdgeInsets.all(40),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text(_error!, style: const TextStyle(color: Colors.orangeAccent)),
                    ),
                  if (w != null) ..._body(w),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _addRow() => ChamferPanel(
    fill: GipsyColors.navyRaised,
    padding: const EdgeInsets.fromLTRB(6, 2, 6, 2),
    child: Row(
      children: [
        Expanded(
          flex: 3,
          child: TextField(
            controller: _newTask,
            decoration: const InputDecoration(hintText: 'Add a task'),
            onSubmitted: (_) => _add(),
          ),
        ),
        Container(width: 1, height: 28, color: GipsyColors.armorShadow),
        Expanded(
          flex: 2,
          child: TextField(
            controller: _newDue,
            decoration: const InputDecoration(hintText: 'Due (friday, 11/30)'),
            onSubmitted: (_) => _add(),
          ),
        ),
        IconButton.filled(tooltip: 'Add', onPressed: _add, icon: const Icon(Icons.add)),
      ],
    ),
  );

  List<Widget> _body(Map<String, dynamic> w) {
    final out = <Widget>[];
    for (final p in (w['problems'] as List? ?? [])) {
      out.add(Text('⚠ $p', style: const TextStyle(color: Colors.orangeAccent, fontSize: 12)));
    }
    if ((w['calendars'] as List? ?? []).isEmpty) {
      out.add(
        const Padding(
          padding: EdgeInsets.only(bottom: 10),
          child: Text(
            'No calendars connected yet. Add your school and personal calendar links to the hub\'s config.json '
            '(see the setup guide), and they\'ll show up here.',
            style: TextStyle(color: GipsyColors.steel, fontSize: 12),
          ),
        ),
      );
    }
    final overdue = (w['overdue'] as List? ?? []).cast<Map<String, dynamic>>();
    if (overdue.isNotEmpty) {
      out.add(
        _dayPanel(
          'OVERDUE',
          '',
          overdue.map((t) => {...t, 'task_id': t['id'], 'date': t['due']}).toList(),
          alert: true,
        ),
      );
    }
    final today = w['start'] as String;
    for (final d in (w['days'] as List).cast<Map<String, dynamic>>()) {
      final items = (d['items'] as List).cast<Map<String, dynamic>>();
      final label = d['date'] == today ? 'TODAY' : (d['weekday'] as String).toUpperCase();
      out.add(_dayPanel(label, _shortDate(d['date'] as String), items));
    }
    final undated = (w['undated'] as List? ?? []).cast<Map<String, dynamic>>();
    if (undated.isNotEmpty) {
      out.add(_dayPanel('ANYTIME', '', undated.map((t) => {...t, 'task_id': t['id']}).toList()));
    }
    return out;
  }

  static const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  String _shortDate(String iso) {
    final p = iso.split('-');
    return '${_months[int.parse(p[1]) - 1]} ${int.parse(p[2])}';
  }

  Widget _dayPanel(String label, String date, List<Map<String, dynamic>> items, {bool alert = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: ChamferPanel(
        accent: label == 'TODAY' || alert,
        border: alert ? GipsyColors.amberDeep : GipsyColors.armorEdge,
        padding: const EdgeInsets.fromLTRB(14, 10, 10, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                TrackedLabel(
                  label,
                  color: alert || label == 'TODAY' ? GipsyColors.amber : GipsyColors.steelBright,
                  size: 12,
                ),
                const SizedBox(width: 8),
                TrackedLabel(date, size: 10),
              ],
            ),
            const SizedBox(height: 6),
            if (items.isEmpty)
              const Padding(
                padding: EdgeInsets.only(bottom: 4),
                child: Text('Nothing scheduled', style: TextStyle(color: GipsyColors.steel, fontSize: 13)),
              ),
            for (final it in items) _item(it),
          ],
        ),
      ),
    );
  }

  Widget _item(Map<String, dynamic> it) {
    final kind = it['kind'] as String? ?? 'calendar';
    final (IconData icon, Color color) = switch (kind) {
      'school' => (Icons.school_outlined, const Color(0xFF7FB2FF)),
      'appointment' => (Icons.event_available_outlined, const Color(0xFF5EE6A0)),
      'fed' => (Icons.account_balance_outlined, GipsyColors.amberHot),
      'econ' => (Icons.insights_outlined, GipsyColors.amber),
      'earnings' => (Icons.trending_up, GipsyColors.amber),
      'task' => (Icons.check_box_outline_blank, GipsyColors.steelBright),
      _ => (Icons.event_outlined, GipsyColors.steel),
    };
    final time = (it['time'] as String? ?? '');
    final sub = [
      if (time.isNotEmpty) _time12(time) + (kind == 'fed' || kind == 'econ' ? ' ET' : ''),
      if ((it['symbol'] as String? ?? '').isNotEmpty) it['symbol'],
      if ((it['location'] as String? ?? '').isNotEmpty) it['location'],
      it['source'] ?? '',
    ].where((s) => (s as String).isNotEmpty).join(' · ');
    final taskId = it['task_id'] as String?;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          if (taskId != null)
            InkWell(
              onTap: () => _done(taskId),
              child: Icon(icon, size: 20, color: color),
            )
          else
            Icon(icon, size: 20, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(it['title'] as String? ?? '', style: const TextStyle(fontSize: 14.5, height: 1.25)),
                if (sub.isNotEmpty) Text(sub, style: const TextStyle(color: GipsyColors.steel, fontSize: 11.5)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _time12(String hhmm) {
    final p = hhmm.split(':');
    var h = int.parse(p[0]);
    final ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 == 0 ? 12 : h % 12;
    return '$h:${p[1]} $ampm';
  }
}
