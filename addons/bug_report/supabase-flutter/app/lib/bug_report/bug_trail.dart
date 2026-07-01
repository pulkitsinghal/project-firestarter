import 'package:flutter/widgets.dart';

/// A single user-action breadcrumb — enough to reconstruct what the user did
/// right before a bug. Keep it small and PII-light.
class BugCrumb {
  final DateTime ts;
  final String type; // your own vocabulary, e.g. 'nav' | 'tap' | 'error'
  final String? route;
  final Map<String, dynamic>? detail;

  BugCrumb(this.type, {this.route, this.detail}) : ts = DateTime.now();

  Map<String, dynamic> toJson() => {
        'ts': ts.toUtc().toIso8601String(),
        'type': type,
        if (route != null) 'route': route,
        if (detail != null) 'detail': detail,
      };
}

/// In-memory ring buffer of recent actions, used to reconstruct a repro at report
/// time. A global singleton so `bugTrail.add(...)` can be called from anywhere —
/// widgets, error branches — without threading a provider through. Never
/// persisted; cleared after a report is sent.
class BugTrail {
  static const _cap = 50;
  final List<BugCrumb> _crumbs = [];

  void add(String type, {String? route, Map<String, dynamic>? detail}) {
    _crumbs.add(BugCrumb(type, route: route, detail: detail));
    if (_crumbs.length > _cap) _crumbs.removeAt(0);
  }

  List<Map<String, dynamic>> toJson() =>
      _crumbs.map((c) => c.toJson()).toList(growable: false);

  bool get isEmpty => _crumbs.isEmpty;

  void clear() => _crumbs.clear();
}

final bugTrail = BugTrail();

/// Feeds Navigator route changes into the trail. Add explicit `bugTrail.add(...)`
/// calls at meaningful actions (a submit, an error branch) for richer signal.
class BugTrailObserver extends NavigatorObserver {
  void _record(String op, Route<dynamic>? route) {
    bugTrail.add('nav', route: route?.settings.name, detail: {'op': op});
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) => _record('push', route);

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) => _record('pop', route);

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) =>
      _record('replace', newRoute);
}
