import 'package:flutter/material.dart';

/// 0 → 1 as `t` moves from `a` to `b`, clamped. Used to stage several animations on one timeline.
double seg(double t, double a, double b) => ((t - a) / (b - a)).clamp(0.0, 1.0).toDouble();

/// Rebuilds its child with a progress value tied to where the widget sits in the scroll
/// viewport, so animations follow the finger like scrubbing a video, forwards and backwards.
///
/// Progress is 0 while the widget's top edge is at `start` × viewport height (1.0 = bottom edge)
/// and 1 once it reaches `end` × viewport height. Negative values measure above the top, which
/// is how the hero fades out as it leaves.
///
/// With the system "reduce motion" setting on, the child is always built at `rest`: the value
/// where it is fully shown (1 for things that animate in, 0 for the hero that animates out).
class ScrollScrub extends StatefulWidget {
  const ScrollScrub({super.key, required this.builder, this.start = 1.0, this.end = 0.6, this.rest = 1.0});

  final Widget Function(BuildContext context, double t) builder;
  final double start;
  final double end;
  final double rest;

  @override
  State<ScrollScrub> createState() => _ScrollScrubState();
}

class _ScrollScrubState extends State<ScrollScrub> {
  ScrollableState? _scrollable;
  ScrollPosition? _position;
  double _t = 0;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _scrollable = Scrollable.maybeOf(context);
    final next = _scrollable?.position;
    if (next != _position) {
      _position?.removeListener(_update);
      _position = next?..addListener(_update);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) => _update());
  }

  @override
  void dispose() {
    _position?.removeListener(_update);
    super.dispose();
  }

  void _update() {
    if (!mounted) return;
    final box = context.findRenderObject();
    final viewport = _scrollable?.context.findRenderObject();
    if (box is! RenderBox || viewport is! RenderBox || !box.attached || !box.hasSize || !viewport.hasSize) return;
    final top = box.localToGlobal(Offset.zero, ancestor: viewport).dy;
    final h = viewport.size.height;
    final t = ((widget.start * h - top) / ((widget.start - widget.end) * h)).clamp(0.0, 1.0).toDouble();
    if ((t - _t).abs() > 0.002) setState(() => _t = t);
  }

  @override
  Widget build(BuildContext context) {
    final still = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return widget.builder(context, still ? widget.rest : _t);
  }
}
