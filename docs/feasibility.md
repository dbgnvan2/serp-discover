# Feasibility scoring — DA thresholds, providers, and pivot logic

Gap = avg competitor DA − client DA. Thresholds:

| Gap | Status | Meaning |
|-----|--------|---------|
| ≤ 5 | ✅ High Feasibility | Rankable with content alone |
| 6–15 | ⚠️ Moderate Feasibility | Requires local backlink building |
| > 15 | 🔴 Low Feasibility | Dominated by high-authority sites — pivot to neighbourhood variant |

**DA providers** (tried in order):
1. **DataForSEO** (`DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD`) — `POST /v3/backlinks/bulk_ranks/live`, up to 1000 domains/call, pay-per-use
2. **Moz** (`MOZ_TOKEN`) — `POST /v2/url_metrics`, up to 50 URLs/call, free tier 50 rows/month

Both cache results in SQLite (`da_cache` and `moz_cache` tables) for 30 days. Re-running within the cache window costs nothing.

**Pivot logic:** Low Feasibility keywords get a neighbourhood variant suggestion (e.g. "Couples Counselling" → "Couples Counselling Lonsdale"). If `feasibility.pivot_serp_fetch: true`, a secondary SerpAPI Maps call checks whether the client appears in the local 3-pack for the pivot keyword.

**Pivots are gated on service intent.** A neighbourhood variant only makes sense for **service-intent** keywords, where physical proximity can substitute for domain authority. Informational keywords (e.g. "how does birth order affect personality") get **no** pivot and **no** neighbourhood variants — nobody searches an informational question with a neighbourhood, and ranking is not the game for them. Service intent is determined by the shared `query_variants.is_service_like` predicate reading the editorial `service_like_tokens` list in `serp_vocab.yml`. Informational Low-Feasibility keywords are reported separately; their play is content extractability, not geography.

**Fetch-failure honesty.** The local-pack signal distinguishes three states: *measured — in local pack* (✓), *measured — genuinely absent* (✗), and *could not measure* (the validation SerpAPI fetch failed). A failed fetch is **never** rendered as "✗ not in local pack" — that would present a transient error as a real negative. When the pivot validation SERP fetch fails entirely, the pivot row is marked **Not Measured** rather than a false "Low Feasibility".
