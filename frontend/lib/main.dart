// lib/main.dart
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

/// バックエンドのベースURLを --dart-define で差し込めます。
/// 例) flutter run -d chrome --dart-define=BACKEND_BASE=https://your-backend
const backendBase = String.fromEnvironment(
  'BACKEND_BASE',
  defaultValue: 'http://127.0.0.1:8000',
);
const apiBase = String.fromEnvironment('API_BASE', defaultValue: '/api');

void main() => runApp(const App());

final _router = GoRouter(
  routes: [
    GoRoute(path: '/', builder: (_, __) => const RankingPage()),
    GoRoute(
      path: '/tool/:slug',
      builder: (context, s) {
        final slug = s.pathParameters['slug']!;
        final name = s.uri.queryParameters['name'];
        final qDays = int.tryParse(s.uri.queryParameters['days'] ?? '');
        return DetailPage(slug: slug, nameHint: name, initialDays: qDays ?? 30);
      },
    )
  ],
);

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) {
    final base = ThemeData(
      useMaterial3: true,
      colorSchemeSeed: const Color(0xFF4F46E5),
      brightness: Brightness.light,
    );

    // Inter でラテン、Noto Sans JP をフォールバックに（CJKはNotoで描画）
    TextStyle _interJP({
      FontWeight? weight,
      double? letterSpacing,
      double? fontSize,
      Color? color,
    }) => GoogleFonts.inter(
      fontWeight: weight,
      letterSpacing: letterSpacing,
      fontSize: fontSize,
      color: color,
    ).copyWith(
      fontFamilyFallback: GoogleFonts.notoSansJp().fontFamilyFallback,
    );

    // ベースを日本語フォントに、見出し/タイトルは Inter(+JP fallback)
    final theme = base.copyWith(
      // ここでアプリ全体の既定フォントを Noto Sans JP に
      textTheme: GoogleFonts.notoSansJpTextTheme(base.textTheme).copyWith(
        headlineSmall: _interJP(weight: FontWeight.w700, letterSpacing: -0.2),
        titleMedium: _interJP(weight: FontWeight.w600),
      ),

      appBarTheme: base.appBarTheme.copyWith(
        centerTitle: true,
        titleTextStyle: _interJP(
          fontSize: 20,
          weight: FontWeight.w700,
          color: base.colorScheme.onSurface,
        ),
      ),

      cardTheme: CardTheme(
        elevation: 0,
        color: base.colorScheme.surface,
        surfaceTintColor: base.colorScheme.primary,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      ),
      chipTheme: base.chipTheme.copyWith(
        side: BorderSide(color: base.colorScheme.outlineVariant),
        labelStyle: _interJP(weight: FontWeight.w600),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      ),
    );

    return MaterialApp.router(
      title: 'Devツール／OSS 毎日更新ランキング',
      locale: const Locale('ja', 'JP'),
      supportedLocales: const [
        Locale('ja', 'JP'),
        Locale('en', 'US'),
      ],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: theme,
      routerConfig: _router,
    );
      }
}

/* ===================== モデル ===================== */

class MiniArticle {
  final String title;
  final String url;
  final int likes;
  final DateTime? publishedAt;

  MiniArticle({
    required this.title,
    required this.url,
    required this.likes,
    this.publishedAt,
  });

  factory MiniArticle.fromJson(Map<String, dynamic> j) => MiniArticle(
        title: j['title'] ?? '',
        url: j['url'] ?? '',
        likes: (j['likes'] as num?)?.toInt() ?? 0,
        publishedAt:
            j['published_at'] != null ? DateTime.tryParse(j['published_at']) : null,
      );
}

class RankingItem {
  final String slug;
  final String name;
  final double score;
  final int articles;
  final int likesSum;
  final List<MiniArticle> articlesTop5;

  RankingItem({
    required this.slug,
    required this.name,
    required this.score,
    required this.articles,
    required this.likesSum,
    this.articlesTop5 = const [],
  });

  factory RankingItem.fromJson(Map<String, dynamic> j) {
    return RankingItem(
      slug: j['slug'] ?? '',
      name: j['name'] ?? '',
      score: (j['score'] as num?)?.toDouble() ?? 0.0,
      articles: (j['articles'] as num?)?.toInt() ?? 0,
      likesSum: (j['likes_sum'] as num?)?.toInt() ?? 0,
      articlesTop5: (j['articles_top5'] as List? ?? [])
          .map((a) => MiniArticle.fromJson(a as Map<String, dynamic>))
          .toList(),
    );
  }
}

/* ===================== 共通UI ===================== */

class RankBadge extends StatelessWidget {
  final int rank;
  const RankBadge({super.key, required this.rank});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        gradient: LinearGradient(colors: [cs.primary, cs.secondary]),
        borderRadius: BorderRadius.circular(12),
      ),
      alignment: Alignment.center,
      child: Text('$rank',
          style: const TextStyle(
              color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16)),
    );
  }
}

class MetricPill extends StatelessWidget {
  final IconData icon;
  final String label;
  const MetricPill({super.key, required this.icon, required this.label});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: cs.surfaceVariant,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: cs.outlineVariant),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 16, color: cs.onSurfaceVariant),
        const SizedBox(width: 6),
        Text(label, style: TextStyle(color: cs.onSurfaceVariant)),
      ]),
    );
  }
}

class ArticleLinks extends StatelessWidget {
  final List<MiniArticle> top5;
  const ArticleLinks({super.key, required this.top5});

  String _fmtDate(DateTime? dt) =>
      dt == null ? '' : DateFormat('yyyy-MM-dd').format(dt);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: List.generate(top5.length, (i) {
        final a = top5[i];
        return Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: InkWell(
            onTap: () =>
                launchUrl(Uri.parse(a.url), mode: LaunchMode.externalApplication),
            child: Row(
              children: [
                Text('${i + 1}. ',
                    style: TextStyle(color: cs.primary, fontWeight: FontWeight.w700)),
                Expanded(
                  child: Text(
                    a.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(decoration: TextDecoration.underline),
                  ),
                ),
                const SizedBox(width: 8),
                if (a.likes > 0)
                  Text('LGTM ${NumberFormat.compact().format(a.likes)}',
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
                if (a.publishedAt != null) ...[
                  const SizedBox(width: 8),
                  Text(_fmtDate(a.publishedAt),
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
                ],
              ],
            ),
          ),
        );
      }),
    );
  }
}

/* ===================== ランキング画面 ===================== */

class RankingPage extends StatefulWidget {
  const RankingPage({super.key});
  @override
  State<RankingPage> createState() => _RankingPageState();
}

class _RankingPageState extends State<RankingPage> {
  bool loading = true;
  List<RankingItem> items = [];
  int days = 30; // 既定は30日
  String? lastUpdated;

  String _fmtJst(String? iso) {
    if (iso == null || iso.isEmpty) return '—';
    final dt = DateTime.tryParse(iso);
    if (dt == null) return '—';
    return DateFormat('yyyy-MM-dd HH:mm').format(dt.toLocal());
    }

  @override
  void initState() {
    super.initState();
    fetchRanking();
  }

  Future<void> fetchRanking() async {
    setState(() => loading = true);

    List data;
    String? updated;

    // ① 静的JSONを優先
    try {
      final r = await http.get(Uri.parse('$apiBase/rankings_$days.json'));
      if (r.statusCode == 200) {
        data = jsonDecode(r.body) as List;
        try {
          final rs = await http.get(Uri.parse('$apiBase/stats_$days.json'));
          if (rs.statusCode == 200) {
            updated = (jsonDecode(rs.body) as Map<String, dynamic>)['last_updated'] as String?;
          }
        } catch (_) {}
      } else {
        throw Exception('static rankings $days not found');
      }
    } catch (_) {
      // ② 失敗したらバックエンドにフォールバック
      final r = await http.get(Uri.parse('$backendBase/rankings?days=$days'));
      data = jsonDecode(r.body) as List;

      try {
        final rs = await http.get(Uri.parse('$backendBase/stats?days=$days'));
        updated = (jsonDecode(rs.body) as Map<String, dynamic>)['last_updated'] as String?;
      } catch (_) {}
    }

    items = data.map((e) => RankingItem.fromJson(e as Map<String, dynamic>)).toList();
    lastUpdated = updated;

    setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          // ヘッダー
          SliverToBoxAdapter(
            child: Container(
              width: double.infinity,
              constraints: const BoxConstraints(minHeight: 140),
              padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 24),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFF4F46E5), Color(0xFF22D3EE)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.auto_awesome, size: 64, color: Colors.white),
                  const SizedBox(height: 16),
                  Text(
                    'Devツール／OSS ランキング100',
                    style: Theme.of(context).textTheme.headlineSmall!.copyWith(
                        color: Colors.white, fontWeight: FontWeight.bold),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Zennでの引用記事数・LGTMを集計。最新トレンドをチェック！',
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium!
                        .copyWith(color: Colors.white70),
                    textAlign: TextAlign.center,
                  ),
                  if (lastUpdated != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      '更新日: ${_fmtJst(lastUpdated)}',
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall!
                          .copyWith(color: Colors.white70),
                    ),
                  ],
                ],
              ),
            ),
          ),

          // 期間切替
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: SegmentedButton<int>(
                segments: const [
                  ButtonSegment(value: 1, label: Text('日間')),
                  ButtonSegment(value: 7, label: Text('週間')),
                  ButtonSegment(value: 30, label: Text('月間')),
                ],
                selected: {days},
                onSelectionChanged: (s) {
                  setState(() => days = s.first);
                  fetchRanking();
                },
              ),
            ),
          ),

          // 本文（セパレータ付き SliverList）
          if (loading)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: Center(child: CircularProgressIndicator()),
            )
          else if (items.isEmpty)
            const SliverFillRemaining(
              hasScrollBody: false,
              child: Center(child: Text('データがありません')),
            )
          else
            SliverList(
              delegate: SliverChildBuilderDelegate(
                (context, idx) {
                  // 仕切り行を入れるため 2n-1 の構成
                  if (idx.isOdd) return const SizedBox(height: 6);
                  final i = idx ~/ 2;
                  final it = items[i];

                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: Card(
                      child: InkWell(
                        borderRadius: BorderRadius.circular(16),
                        onTap: () => context.push(
                          '/tool/${it.slug}?name=${Uri.encodeComponent(it.name)}&days=$days'
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              RankBadge(rank: i + 1),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    // タイトル & スコア
                                    Row(
                                      children: [
                                        Expanded(
                                          child: Text(
                                            it.name,
                                            style: Theme.of(context)
                                                .textTheme
                                                .titleMedium,
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        MetricPill(
                                          icon: Icons.trending_up,
                                          label:
                                              'Score ${it.score.toStringAsFixed(2)}',
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 6),
                                    // メトリクス
                                    Wrap(
                                      spacing: 8,
                                      runSpacing: 6,
                                      children: [
                                        MetricPill(
                                          icon: Icons.article_outlined,
                                          label:
                                              '記事 ${NumberFormat.compact().format(it.articles)}',
                                        ),
                                        MetricPill(
                                          icon: Icons.favorite,
                                          label:
                                              'LGTM ${NumberFormat.compact().format(it.likesSum)}',
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: 10),
                                    // 記事トップ5（リンク付き）
                                    if (it.articlesTop5.isNotEmpty)
                                      ArticleLinks(top5: it.articlesTop5)
                                    else
                                      Text('最近の記事は見つかりませんでした',
                                          style: Theme.of(context)
                                              .textTheme
                                              .bodySmall),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                },
                childCount: items.isEmpty ? 0 : items.length * 2 - 1,
              ),
            ),
        ],
      ),
    );
  }
}

/* ===================== 詳細ページ ===================== */

class DetailPage extends StatefulWidget {
  final String slug;
  final String? nameHint;
  final int initialDays;
  const DetailPage({super.key, required this.slug, this.nameHint, this.initialDays = 30});

  @override
  State<DetailPage> createState() => _DetailPageState();
}

class _DetailPageState extends State<DetailPage> {
  Map<String, dynamic>? data;
  bool loading = true;
  late int days;

  @override
  void initState() {
    super.initState();
    days = widget.initialDays; 
    fetchDetail();
  }

  Future<void> fetchDetail() async {
    setState(() => loading = true);
    try {
      // ① 静的JSONを優先
      final urlStatic = Uri.parse('$apiBase/tools/${widget.slug}-${days}.json');
      final rs = await http.get(urlStatic);
      if (rs.statusCode == 200) {
        data = jsonDecode(rs.body) as Map<String, dynamic>;
      } else {
        // ② 失敗したらバックエンドへ
        final urlApi = Uri.parse('$backendBase/tool/${widget.slug}?days=$days');
        final ra = await http.get(urlApi);
        if (ra.statusCode != 200) {
          throw Exception('detail not found (static:${rs.statusCode}, api:${ra.statusCode})');
        }
        data = jsonDecode(ra.body) as Map<String, dynamic>;
      }
    } catch (e) {
      data = {
        'tool': {'slug': widget.slug, 'name': widget.nameHint ?? widget.slug},
        'metric': {'score': 0, 'articles': 0, 'likes_sum': 0, 'date': null},
        'articles_top': <dynamic>[],
        'error': e.toString(),
      };
    } finally {
      setState(() => loading = false);
    }
  }

  String _fmtDate(DateTime? dt) =>
      dt == null ? '—' : DateFormat('yyyy-MM-dd').format(dt);

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (data == null || data!['tool'] == null) {
      return const Scaffold(body: Center(child: Text('データが見つかりませんでした')));
    }

    final tool = data!['tool'] as Map<String, dynamic>;
    final metric = data!['metric'] as Map<String, dynamic>? ?? {};
    final arts = (data!['articles_top'] as List? ?? [])
        .map((e) => MiniArticle.fromJson(e as Map<String, dynamic>))
        .toList();

    final toolName = tool['name'] ?? widget.nameHint ?? widget.slug;

    return Scaffold(
      appBar: AppBar(title: Text(toolName)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 期間切替（任意：あると便利）
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              const Text('期間: '),
              DropdownButton<int>(
                value: days,
                items: const [
                  DropdownMenuItem(value: 1, child: Text('1日')),
                  DropdownMenuItem(value: 7, child: Text('7日')),
                  DropdownMenuItem(value: 30, child: Text('30日')),
                ],
                onChanged: (v) {
                  if (v == null) return;
                  setState(() => days = v);
                  fetchDetail(); // ← days を付けて再取得（fetchDetail内で ?days=$days を呼ぶ実装）
                },
              ),
            ],
          ),

          // 指標
          Text(toolName, style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _Badge(
                icon: Icons.score,
                label: 'スコア',
                // ✅ 型安全にしてから toStringAsFixed(2)
                value: ((metric['score'] as num?)?.toDouble() ?? 0).toStringAsFixed(2),
              ),
              _Badge(
                icon: Icons.article_outlined,
                label: '記事',
                value: '${metric['articles'] ?? 0}',
              ),
              _Badge(
                icon: Icons.favorite,
                label: 'LGTM合計',
                value: '${metric['likes_sum'] ?? 0}',
              ),
            ],
          ),
          const SizedBox(height: 16),

          // 記事一覧
          Text('最近の記事', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (arts.isEmpty)
            const Text('最近の関連記事は見つかりませんでした')
          else
            ...arts.map(
              (a) => Card(
                margin: const EdgeInsets.only(bottom: 10),
                child: ListTile(
                  leading: const Icon(Icons.link),
                  title: Text(
                    a.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text(
                    [
                      if (a.likes > 0) 'LGTM ${a.likes}',
                      if (a.publishedAt != null) _fmtDate(a.publishedAt),
                    ].join(' ・ '),
                  ),
                  onTap: () => launchUrl(Uri.parse(a.url),
                      mode: LaunchMode.externalApplication),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  const _Badge({required this.icon, required this.label, required this.value});
  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 18),
      label: Text('$label: $value'),
      padding: const EdgeInsets.symmetric(horizontal: 8),
    );
  }
}
