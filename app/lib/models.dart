/// Plain data classes mirroring the Supabase tables the app may read.
library;

enum Stance { bullish, neutral, bearish }

Stance parseStance(Object? s) =>
    Stance.values.firstWhere((e) => e.name == s, orElse: () => Stance.neutral);

extension StanceText on Stance {
  String get label => switch (this) {
        Stance.bullish => 'Bullish',
        Stance.neutral => 'Neutral',
        Stance.bearish => 'Bearish',
      };

  /// A shape as well as a colour, so stance never depends on colour alone.
  String get mark => switch (this) {
        Stance.bullish => '▲',
        Stance.neutral => '■',
        Stance.bearish => '▼',
      };
}

/// How a view compares with the previous good run.
enum Change { unknown, isNew, changed, unchanged }

class AgentRun {
  const AgentRun({required this.id, required this.asOf, required this.status, this.model});

  final int id;
  final String asOf;
  final String status;
  final String? model;

  factory AgentRun.fromJson(Map<String, dynamic> j) => AgentRun(
        id: (j['id'] as num).toInt(),
        asOf: j['as_of'].toString(),
        status: j['status'].toString(),
        model: j['model'] as String?,
      );
}

final _chunkRef = RegExp(r'^chunk_(\d+)$');

class Suggestion {
  Suggestion({
    required this.id,
    required this.ticker,
    required this.horizon,
    required this.stance,
    required this.thesis,
    required this.risks,
    required this.sources,
    required this.confidence,
    required this.asOf,
    this.runId,
  });

  final int id;
  final int? runId;
  final String ticker;
  final String horizon; // 'medium' (1–3 months) or 'long' (6–24 months)
  final Stance stance;
  final String thesis;
  final List<String> risks;
  final List<String> sources;
  final double confidence;
  final String asOf;

  Change change = Change.unknown;
  Stance? previousStance;

  String get key => '$ticker|$horizon';
  String get horizonLabel => horizon == 'medium' ? '1–3 months' : '6–24 months';

  /// `chunk_123` references as ids; anything malformed is ignored.
  List<int> get chunkIds => [
        for (final s in sources)
          if (_chunkRef.firstMatch(s) case final m?) int.parse(m.group(1)!),
      ];

  factory Suggestion.fromJson(Map<String, dynamic> j) => Suggestion(
        id: (j['id'] as num).toInt(),
        runId: (j['run_id'] as num?)?.toInt(),
        ticker: j['ticker'].toString(),
        horizon: j['horizon'].toString(),
        stance: parseStance(j['stance']),
        thesis: (j['thesis'] ?? '').toString(),
        risks: [for (final r in (j['risks'] as List? ?? const [])) r.toString()],
        sources: [for (final s in (j['sources'] as List? ?? const [])) s.toString()],
        confidence: (j['confidence'] as num? ?? 0).toDouble(),
        asOf: j['as_of'].toString(),
      );
}

/// Only http(s) links ever become tappable.
String? safeUrl(Object? url) {
  final s = url?.toString();
  if (s == null) return null;
  final uri = Uri.tryParse(s);
  return uri != null && (uri.scheme == 'https' || uri.scheme == 'http') && uri.host.isNotEmpty ? s : null;
}

class Citation {
  const Citation({
    required this.id,
    required this.ticker,
    required this.source,
    required this.publishedAt,
    required this.content,
    this.docType,
    this.title,
    this.url,
  });

  final int id;
  final String ticker;
  final String source;
  final String? docType;
  final String publishedAt;
  final String content;
  final String? title;
  final String? url;

  String get date => publishedAt.length >= 10 ? publishedAt.substring(0, 10) : publishedAt;
  String get label => '${docType ?? source} $date';

  factory Citation.fromJson(Map<String, dynamic> j) => Citation(
        id: (j['id'] as num).toInt(),
        ticker: j['ticker'].toString(),
        source: j['source'].toString(),
        docType: j['doc_type'] as String?,
        publishedAt: j['published_at'].toString(),
        content: (j['content'] ?? '').toString(),
        title: j['title'] as String?,
        url: safeUrl(j['url']),
      );
}

class PricePoint {
  const PricePoint(this.date, this.price);

  final DateTime date;
  final double price;

  /// Prefers the dividend/split-adjusted close; rows with neither close are dropped.
  static PricePoint? fromJson(Map<String, dynamic> j) {
    final v = (j['adj_close'] ?? j['close']) as num?;
    final d = DateTime.tryParse(j['date'].toString());
    return v == null || d == null || v <= 0 ? null : PricePoint(d, v.toDouble());
  }
}
