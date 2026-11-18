# Chunk Y14 — one cache for both keyword signals

Carried as "Adjacent issues found, not fixed" by chunk Y11's cold review and
repeated in the Y12 and Y13 plans.

## The fault

`moz_keywords._KeywordSignalClient` exists because the fetch, quota and
"404 is not an error" rules had to behave identically for both per-keyword Moz
signals, and a fix to one must not miss the other (P5). The **cache** was left
out of it. `MozKeywordClient` and `MozIntentClient` each carry their own
`_init_cache_table`, `_cache_lookup` and `_cache_store`, and the three rules
that matter are written twice:

1. **The TTL cutoff.** A row older than `cache_ttl_days` is ignored.
2. **Never serve a cached failure.** A row whose `status` is neither `ok` nor
   `no_record` is skipped, so a keyword whose last fetch errored is re-fetched
   rather than reported as absent for a month.
3. **A measured absence is cached.** `no_record` is served from cache as an
   absent block, so a keyword Moz holds nothing for is not re-bought every run.

Each is one `continue` in a loop that is otherwise identical: the same chunked
`IN (...)` SELECT on the same key (`keyword, engine, locale, device`), the same
`to_fetch` difference, the same `INSERT OR REPLACE` filtered by the same
`_CACHEABLE` set. What actually differs between the two signals is four things:
the table name, the payload columns, how a row becomes a block, and how a block
becomes a row.

The duplication has already drifted in one way that shows the risk: both moz
caches chunk their `IN (...)` at a bare literal `500`, while `gsc_client` — the
third cache of this shape in the repo — names the same number
`CACHE_LOOKUP_CHUNK` and records why it exists (SQLite caps bound variables at
999 in older builds). Three copies of one fact about SQLite, one of them
explained and two of them not (P4/P32).

## What is built

**The base class owns the cache.** `_KeywordSignalClient` gains the table
spec — `CACHE_TABLE_NAME` and `CACHE_PAYLOAD_COLUMNS` (name and SQLite type
per column) — and the three methods built from it: the DDL, the chunked
lookup with the three rules above, and the store. Each subclass supplies only
`_block_from_cache(values)` and `_payload_for_cache(block)`, the two
signal-specific halves.

**The chunk size is named once.** `db_connect.CACHE_LOOKUP_CHUNK`, since it is
a fact about SQLite's bound-variable limit rather than about Moz or about
Search Console, and `gsc_client` reads it from there too.

**No behaviour changes.** This is a refactor: the same SQL on the same tables,
the same cached blocks, the same rows written. The existing `test_moz_*` and
`test_moz_intent` suites are the regression evidence, and the new tests assert
the three rules once against *both* clients, which is the point — a rule
asserted against one class was how a divergence could pass.

## Verification

Full suite by exit code, plus the mutation gate: each production change
reverted on its own must fail a guard covering its own criterion. The guards
are consequences — a stale row, an errored row and a `no_record` row put in the
cache table, then what each client returns — run against both subclasses
through the same parametrised test, so neither can drift from the other
unnoticed.

## What is NOT in this chunk

* `gsc_client`'s own cache keeps its own lookup: it answers a three-way split
  (found / measured-absent / never-reached) over a different key (date range
  plus filters), and folding it into the keyword base class would mean one
  method serving two different questions.
* The adjacent issues still open: a `config_manager` tab for the Y1–Y6
  editorial keys, Tool 2's two divergent `shared_config.json` readers and its
  double read per `DatabaseManager`, Tool 2 having no editorial text file at
  all, and the untracked `keyword_enrich.py`.

## Cold review and what it changed

A cold `learning-qa` pass over the diff raised six findings: one high, three
medium, two informational. It verified independently that the generated DDL is
byte-equivalent to both removed hand-written tables (`PRAGMA table_info`
compared column by column, including declared types, `NOT NULL` and PK
ordinals), that the removed per-subclass `conn.commit()` calls are covered by
`db_connect.connection`, that the placeholder arithmetic and the
SELECT↔unpack column order are right, and that `gsc_client` behaves as before.
Every medium-or-higher finding was fixed with a guard.

**F1 (high) — the chunk's own rule stopped at two of five call sites.** Three
more production caches batch an `IN (...)` lookup of exactly this shape and
still carried the bare literal `500`: `moz_client` (URL/DA cache),
`dataforseo_client` (domain DA cache) and `moz_competitor` (per-signal
competitor cache). So `db_connect.CACHE_LOOKUP_CHUNK` could be changed and
three caches would not follow, raising `too many SQL variables` on a large run
— and in the brief path that is caught and reported as "signal unavailable".
`docs/architecture.md` also claimed the chunk had covered the field, which it
had not (P6). All three now read the named constant, the doc says five, and the
guard was replaced: it walks every production module with an AST and fails on
any chunked lookup carrying its own number, rather than checking two files by
name. A list of names is how the sixth cache gets missed.

**F2 (medium) — a payload-column change had no migration and no mismatch
check.** `CREATE TABLE IF NOT EXISTS` does not alter an existing table, and
adding a cached column is now a one-line edit to `CACHE_PAYLOAD_COLUMNS` that
reads as harmless. Every developer with a fresh database would be fine while
every existing installation failed on the first write with `table ... has no
column named ...`, which `brief_rendering` catches and reports as the signal
being unavailable for every keyword, every run — a local schema drift
presenting as a permanently absent paid signal. `_add_missing_columns` now
adds any declared column the live table lacks, keeping the rows: a row that
predates the column reads it as NULL, which every consumer already treats as
"not held". A column the spec has dropped is left alone, because every query
here names its columns.

**F3 (medium) — the column order was a second, unwritten contract.** The hooks
exchanged a positional tuple, so reordering `CACHE_PAYLOAD_COLUMNS` —
alphabetising it, say — would have handed every keyword its neighbour's figure,
with no value out of range to notice. For the intent signal the damage was
silent in a second way: `_decode_json` emptied a blob of the wrong shape with
no log, so every cached keyword would report `primary_intents: []` and read as
"Moz has no opinion" rather than as a bug. The hooks now exchange a mapping
keyed by column name, so the order carries no meaning at all — proved by a
test that runs a subclass with the columns reversed and asserts a reader sees
the same block — and the shape mismatch is logged.

**F4 (medium) — a cached row the signal could not read was dropped silently.**
No subclass returns `None` today, so there was no live defect, but such a row
is re-fetched, which costs billed Moz rows every run while the cache appears
simply not to hit. The count is now stated as "N of M".

**F5 (medium) — an incomplete subclass spec failed opaquely.** An empty
`CACHE_TABLE_NAME` raised `near "(": syntax error` at construction; an empty
`CACHE_PAYLOAD_COLUMNS` was worse — it created a real table and failed on the
first lookup. Neither named the class or the attribute, and the message a user
saw came through `brief_rendering`'s handler. `_init_cache_table` now raises
`NotImplementedError` naming both.

**F6 (informational) — f-string SQL.** Not exploitable: both attributes are
class-level and `from_config` never sources them from config. A comment now
says so, because the code reads as a generic table builder and this repo's
editorial rule would otherwise invite promoting such a spec into YAML, which
would be direct SQL injection with no parameterisation available.

**Mutation gate:** 30 mutations, 30 caught, 0 vacuous. One mutation was
withdrawn rather than counted: removing the payload columns from the generated
DDL is now a no-op, because `_add_missing_columns` repairs the table. The DDL's
contribution is covered by "a payload column is invented" and by the two F2
mutations.

## Adjacent issues found, not fixed

* **`_decode_json` is named for the intent cache.** It logs
  `INTENT_CACHE_TABLE` regardless of caller, which is correct today because
  only `MozIntentClient` calls it. A second JSON-payload signal would get a
  misattributed warning.
* **`test_the_table_is_created_with_this_signals_columns` compares a column
  set, not the declared types or `NOT NULL`.** Harmless here, since every
  query names its columns and SQLite does not enforce declared types, but it
  is weaker than the guard reads.
* The adjacent issues carried forward: no `config_manager` tab for ten of the
  nineteen editorial files (planned as chunk Y15,
  `PLAN_Y15_every_editorial_file_has_an_editor.md`), Tool 2's two divergent
  `shared_config.json` readers and its double read per `DatabaseManager`,
  Tool 2 having no editorial text file at all, and the untracked
  `keyword_enrich.py`.
