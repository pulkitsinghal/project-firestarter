// {{ project_name }} — Flutter app entrypoint (skeleton).
// Grow this into your real app. Keep the faith/domain source of truth in the
// service layer (../services), not scattered across widgets.

import 'package:flutter/material.dart';

void main() => runApp(const PilgrimApp());

class PilgrimApp extends StatelessWidget {
  const PilgrimApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '{{ project_name }}',
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
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
      body: const Center(child: Text('{{ project_tagline }}')),
    );
  }
}
