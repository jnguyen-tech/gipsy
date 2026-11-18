import 'package:flutter/material.dart';

import 'hub_client.dart';
import 'theme.dart';

/// Link school and personal calendars (iCal feeds) from the app, so John
/// doesn't have to edit config.json on the PC.
Future<void> showCalendarsSheet(BuildContext context, HubClient hub) => showModalBottomSheet<void>(
  context: context,
  isScrollControlled: true,
  backgroundColor: GipsyColors.navyRaised,
  builder: (_) => CalendarsSheet(hub: hub),
);

class CalendarsSheet extends StatefulWidget {
  const CalendarsSheet({super.key, required this.hub});
  final HubClient hub;

  @override
  State<CalendarsSheet> createState() => _CalendarsSheetState();
}

class _CalendarsSheetState extends State<CalendarsSheet> {
  List<Map<String, dynamic>> _cals = [];
  final _name = TextEditingController();
  final _url = TextEditingController();
  String _kind = 'school';
  String? _msg;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _name.dispose();
    _url.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final c = await widget.hub.calendars();
      if (mounted) setState(() => _cals = c);
    } catch (e) {
      if (mounted) setState(() => _msg = e.toString());
    }
  }

  Future<void> _link() async {
    setState(() {
      _busy = true;
      _msg = null;
    });
    try {
      final r = await widget.hub.linkCalendar(_name.text, _url.text, _kind);
      _msg = r['ok'] == true
          ? 'Linked "${r['name']}". It shows up in This week now.'
          : 'Saved, but the test download failed (${r['error']}). Check the link, or unlink it.';
      _name.clear();
      _url.clear();
      await _refresh();
    } catch (e) {
      _msg = e.toString();
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _unlink(String id) async {
    try {
      await widget.hub.unlinkCalendar(id);
    } catch (e) {
      _msg = e.toString();
    }
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const TrackedLabel('Linked calendars', color: GipsyColors.amber, size: 13),
            const SizedBox(height: 8),
            if (_cals.isEmpty)
              const Text('None yet.', style: TextStyle(color: GipsyColors.steel))
            else
              for (final c in _cals)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(c['kind'] == 'school' ? Icons.school_outlined : Icons.event_outlined),
                  title: Text('${c['name']}'),
                  subtitle: Text(
                    c['removable'] == true ? '${c['url']}' : '${c['url']} · set in config.json',
                    style: const TextStyle(fontSize: 11, color: GipsyColors.steel),
                  ),
                  trailing: c['removable'] == true
                      ? IconButton(
                          tooltip: 'Unlink',
                          icon: const Icon(Icons.link_off),
                          onPressed: () => _unlink('${c['id']}'),
                        )
                      : null,
                ),
            const Divider(height: 28),
            const TrackedLabel('Add a calendar link', color: GipsyColors.steelBright, size: 11),
            const SizedBox(height: 8),
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name, e.g. Canvas or My calendar')),
            TextField(
              controller: _url,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: 'iCal link (https:// or webcal://)'),
            ),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'school', label: Text('School'), icon: Icon(Icons.school_outlined)),
                ButtonSegment(value: 'appointment', label: Text('Appointments'), icon: Icon(Icons.event_outlined)),
                ButtonSegment(value: 'calendar', label: Text('Other')),
              ],
              selected: {_kind},
              onSelectionChanged: (s) => setState(() => _kind = s.first),
            ),
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: _busy ? null : _link,
              icon: const Icon(Icons.add_link),
              label: Text(_busy ? 'Testing the link...' : 'Link it'),
            ),
            if (_msg != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_msg!, style: const TextStyle(color: GipsyColors.amber, fontSize: 12)),
              ),
            const SizedBox(height: 12),
            const Text(
              'Where to find the link:\n'
              '• Canvas: Calendar, then Calendar Feed (bottom right)\n'
              '• Google Calendar or Classroom: Settings, pick the calendar, then "Secret address in iCal format"\n'
              '• Schoology: Calendar, then Export\n'
              '• Outlook: Settings, Calendar, Shared calendars, Publish a calendar, then the ICS link\n'
              'The link stays on your PC. Treat it like a password.',
              style: TextStyle(color: GipsyColors.steel, fontSize: 12, height: 1.5),
            ),
          ],
        ),
      ),
    );
  }
}
