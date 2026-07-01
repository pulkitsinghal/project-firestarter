import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

/// Key on the RepaintBoundary wrapping the capturable screen (see ScreenshotBoundary).
final GlobalKey screenshotBoundaryKey = GlobalKey();

/// Wrap the screen content you want a bug report to be able to snapshot.
/// Dependency-free: just a keyed RepaintBoundary (no `screenshot` package).
class ScreenshotBoundary extends StatelessWidget {
  final Widget child;
  const ScreenshotBoundary({super.key, required this.child});

  @override
  Widget build(BuildContext context) =>
      RepaintBoundary(key: screenshotBoundaryKey, child: child);
}

/// Best-effort base64 PNG of the boundary's current pixels. Returns null if the
/// boundary isn't mounted/painted yet or the platform can't rasterize — callers
/// treat a null shot as "no screenshot", never an error.
Future<String?> captureScreenshotBase64({double pixelRatio = 1.5}) async {
  try {
    final render = screenshotBoundaryKey.currentContext?.findRenderObject();
    if (render is! RenderRepaintBoundary) return null;
    final image = await render.toImage(pixelRatio: pixelRatio);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    if (bytes == null) return null;
    return base64Encode(bytes.buffer.asUint8List());
  } catch (_) {
    return null;
  }
}
