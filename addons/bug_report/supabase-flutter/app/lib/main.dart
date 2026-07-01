// {{ project_name }} — Flutter app entrypoint (bug-report add-on enabled).
// Adds an in-app "Report a bug" flow: a breadcrumb trail (BugTrailObserver) plus
// a capture sheet that files a structured report via the report_bug RPC. Grow
// this into your real app; keep the domain source of truth in ../services.

import 'package:flutter/material.dart';

import 'bug_report/bug_report.dart';
import 'bug_report/bug_trail.dart';
import 'bug_report/screenshot.dart';

void main() => runApp(const PilgrimApp());

class PilgrimApp extends StatelessWidget {
  const PilgrimApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '{{ project_name }}',
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
      navigatorObservers: [BugTrailObserver()],
      home: const HomePage(),
    );
  }
}

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('{{ project_name }}')),
      // Wrapped so the bug-report flow can snapshot exactly what's on screen.
      body: const ScreenshotBoundary(child: Center(child: Text('{{ project_tagline }}'))),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => openBugReport(context, route: '/'),
        icon: const Icon(Icons.bug_report_outlined),
        label: const Text('Report a bug'),
      ),
    );
  }
}
