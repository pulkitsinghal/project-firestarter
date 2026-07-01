import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';

import 'bug_trail.dart';

/// PostgREST base URL. Defaults to the local stack's API port; override at build
/// time: `flutter run --dart-define=API_BASE=https://api.example.com`.
const _apiBase =
    String.fromEnvironment('API_BASE', defaultValue: 'http://localhost:{{ port_api }}');
const _appVersion = '0.1.0';

/// A device id for this install. Random v4 per launch in this skeleton — persist
/// it (e.g. shared_preferences) if you want continuity across sessions.
final String _deviceId = _uuidV4();

String _uuidV4() {
  final r = Random();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // variant
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

/// POST the report to PostgREST's `report_bug` RPC (anon role). Returns the new
/// report id, or null on failure (best-effort — never blocks the user).
Future<String?> submitBugReport({
  required String title,
  required String route,
  Map<String, dynamic>? snapshot,
}) async {
  final payload = <String, dynamic>{
    'p_device_id': _deviceId,
    'p_title': title,
    'p_route': route,
    'p_app_version': _appVersion,
    'p_breadcrumbs': bugTrail.toJson(),
    'p_snapshot': snapshot ?? <String, dynamic>{'route': route},
    'p_screenshot': null, // attach a base64 PNG here if you add screenshot capture
  };
  final client = HttpClient();
  try {
    final req = await client.postUrl(Uri.parse('$_apiBase/rpc/report_bug'));
    req.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    req.add(utf8.encode(jsonEncode(payload)));
    final resp = await req.close();
    final body = await resp.transform(utf8.decoder).join();
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      bugTrail.clear();
      return body.replaceAll('"', '').trim(); // the returned uuid
    }
    return null;
  } catch (_) {
    return null;
  } finally {
    client.close();
  }
}

/// Open the review/consent sheet for the current screen.
Future<void> openBugReport(BuildContext context, {String route = '/'}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => BugReportSheet(route: route),
  );
}

class BugReportSheet extends StatefulWidget {
  final String route;
  const BugReportSheet({super.key, required this.route});

  @override
  State<BugReportSheet> createState() => _BugReportSheetState();
}

class _BugReportSheetState extends State<BugReportSheet> {
  final _title = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    setState(() => _sending = true);
    final id = await submitBugReport(title: _title.text.trim(), route: widget.route);
    if (!mounted) return;
    setState(() => _sending = false);
    Navigator.of(context).pop();
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(id != null
          ? 'Thanks — bug captured (ref ${id.length >= 8 ? id.substring(0, 8) : id})'
          : "Couldn't send the report. Please try again."),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 16, 20, 16 + bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Report a bug',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          const Text('We capture what you just did so we can reproduce and fix '
              'it — no need to explain it perfectly.'),
          const SizedBox(height: 16),
          TextField(
            controller: _title,
            maxLength: 200,
            decoration: const InputDecoration(hintText: 'What went wrong? (optional)'),
          ),
          const SizedBox(height: 8),
          const Text('Includes your recent in-app actions (breadcrumbs) and the current screen.',
              style: TextStyle(fontSize: 12)),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: _sending ? null : _send,
              child: _sending
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Send report'),
            ),
          ),
        ],
      ),
    );
  }
}
