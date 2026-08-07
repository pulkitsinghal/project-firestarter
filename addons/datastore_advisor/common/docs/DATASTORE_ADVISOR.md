# Choosing a datastore for {{ project_name }}

Most projects inherit a datastore. The scaffold ships one, the tutorial used one,
the last project used one — and the decision that shapes everything downstream
gets made by default rather than on purpose.

This guide exists so that {{ project_slug }} makes it on purpose. It is a
decision aid, not a ruling: it gives you a recommendation, the reasoning behind
it, the case against it, and an explicit list of what would change the answer.
**You make the call.** The tool argues both sides so that you can.

Run it:

```bash
python3 -m tools.datastore_advisor.cli
python3 -m tools.datastore_advisor.cli --explain postgres
```

It writes a decision record you commit next to your code
([docs/DATASTORE_DECISION.md](DATASTORE_DECISION.md)), so the reasoning survives
the person who did the reasoning.

---

## The short version

**For most projects, the answer is PostgreSQL, and that is not a cop-out.** A
single well-indexed Postgres instance covers relational data, documents (JSONB),
key-value lookups, full-text search, geospatial queries, job queues, and — with
the `pgvector` extension — semantic search, behind one backup, one transaction
boundary, and one thing to learn. It is the most portable option in this guide
and the easiest to hire for.

If that is your answer, take it and go build the product. Reaching for anything
else should require a reason you can state in one sentence, and this guide is
mostly about testing whether that sentence survives contact with the details.

The three ways this decision usually goes wrong:

1. **Over-engineering.** Buying distributed-systems complexity for a workload one
   node handles comfortably. The complexity is paid every day thereafter; the
   scale it was bought for often never arrives.
2. **Choosing an engine for a property it does not have in the edition you will
   run.** See [the edition trap](#the-edition-trap), below. This one is
   invisible until an audit.
3. **Never asking whether you should hold the data at all.** See
   [the first question](#the-first-question-do-you-even-want-to-hold-it).

---

## The first question: do you even want to hold it?

Ask this before anything else, because it changes every answer below it.

For a real class of products, the correct place for the user's data is the
user's device — or your server, but encrypted with a key you do not have. When
the operator holds nothing readable, an entire category of liability stops
existing rather than being managed:

- No breach can disclose records you never had.
- No subject-access export to build, because you cannot read it either.
- No server-side retention policy to enforce, audit, and get wrong.
- No key custody problem, because you hold no keys.

This is genuinely cheaper — in engineering, in compliance, and in risk — than
holding data well. It is also a real product constraint, not a free win, and the
constraint is severe:

- **Anything the server must compute over is out.** Search, ranking,
  recommendations, moderation, aggregate analytics — all of these need readable
  data.
- **Sharing between users becomes key distribution**, which is hard to get right.
- **Server-side account recovery generally becomes impossible.** If you cannot
  read the data, you cannot recover it when the user loses their key. This is the
  most common reason teams abandon the approach, and it must be decided before
  launch rather than after the first support ticket.
- **Partial versions give you nothing.** If your server holds the keys, or sees
  plaintext in a log, a crash report, an analytics payload, or a backup, you do
  not have the property — whatever the marketing page says. Trace one real record
  through the entire system before claiming it.

If the honest answer is "we need the server to read this", say so and move on.
The point is to have answered it deliberately.

---

## The axes that actually matter

### Workload shape

Pick the shape from what your **queries** do, not from what the domain sounds
like. Nearly every domain can be described as a graph, or as documents, in
conversation. The running queries are the evidence.

| Shape | What it looks like | Usual answer |
|---|---|---|
| Relational | Entities with relationships, filtered and joined | Postgres |
| Document | Self-contained records with varying fields, fetched whole | Postgres JSONB first; a document store if you have outgrown it |
| Key-value | Fetch an opaque value by known key, very fast | Postgres, or a cache in front of it; DynamoDB at real scale |
| Graph | See the reality check below | Almost always Postgres |
| Vector | Semantic / similarity search | Postgres + pgvector |
| Time-series | Append-mostly measurements, queried by window | Postgres, plus an extension if ingest is extreme |
| Blob | Images, audio, video, archives | Object storage, with a URL in the row — never the database |

### The graph reality check

This deserves its own section because it is where the most expensive version of
this mistake happens, and because it is trivially checkable in advance.

Answer three questions with numbers, not adjectives:

1. **Edge density.** Count your relationship rows. Divide by your entity rows.
   Around 1 or below means you have a foreign key, not a graph.
2. **Traversal depth.** How many hops does your deepest *routine* query need?
   One hop is a join. Two hops is a join. Variable or unbounded depth is where a
   graph engine's index-free adjacency genuinely beats a relational plan, because
   the relational cost compounds per hop and the graph cost does not.
3. **Named algorithms.** Which graph algorithms will you actually run —
   PageRank, community detection, shortest path, centrality, cycle detection? If
   the honest answer is "none, we follow links and render them", the traversal
   engine is never invoked.

A workload measuring **sparse, single-hop, and no algorithms** is a relational
workload. Choosing a graph database for it buys a distinct query language, a
thinner operational literature, a smaller hiring pool, and a high exit cost, in
exchange for a traversal advantage you never collect.

Choose a graph database when the numbers say graph. They sometimes do, and when
they do it is genuinely the better tool.

### Scale, honestly measured

Thousands of rows is not millions. Millions is not billions.

A single well-indexed relational node handles far more than most teams assume.
Before concluding that you have outgrown it, measure — because the alternative is
paying distributed-systems complexity every day for a scale that may never
arrive. "We might get big" is not a measurement.

If you genuinely do not know your scale yet, that is not an argument for a bigger
system. **It is an argument for the most portable one**, so that the decision is
cheap to revisit once you have evidence.

### Traffic profile — and when scale-to-zero is real

This is the axis that decides whether "serverless" is worth paying attention to.

- **Idle most of the time** — pre-launch products, internal tools, per-developer
  environments, seasonal workloads. A provider that suspends idle compute is a
  real saving here. This is the case for something like Neon.
- **Steady** — compute never suspends, so scale-to-zero is *inert*. Judge
  providers on price, support, and features that actually fire. Do not pay a
  premium for a capability that will never trigger.
- **Sparse and latency-sensitive at once** — the worst combination. Waking
  suspended compute takes time (Neon documents a few hundred milliseconds), and
  that lands on a user-facing request. Decide deliberately whether to keep
  compute warm; do not discover it in production.

### Isolation, compliance — and the edition trap

Name the isolation **mechanism**, not the intention. "Each customer is separate"
is an intention. A row filter, a schema, a database, or a cluster is a mechanism.

#### The edition trap

**Verify that the edition you will actually run has the feature you are choosing
the engine for.**

This is the single most valuable check in this guide, and it takes five minutes.

The properties teams most often select an engine for — separating data into
distinct databases, role-based access control, fine-grained authorisation, online
backup, audit logging, encryption at rest — are frequently gated to a paid or
enterprise edition. Meanwhile, the edition that gets installed to evaluate the
thing, and then quietly stays in production, is the free or community one.

A concrete, checkable example. Neo4j's own operations manual documents that:

- Community Edition installations "can have exactly **one** standard database";
  Enterprise Edition "can have **any number**"
  ([docs](https://neo4j.com/docs/operations-manual/current/database-administration/),
  read 2026-08-07).
- Authorization via role-based access control is documented under an
  **Enterprise Edition** banner; Community gets only "a limited set of user
  management functions"
  ([docs](https://neo4j.com/docs/operations-manual/current/authentication-authorization/),
  read 2026-08-07).
- Community can back up an **offline** database; **online** (hot) backup is
  Enterprise
  ([docs](https://neo4j.com/docs/operations-manual/current/backup-restore/),
  read 2026-08-07).
- Community Edition is GPLv3; Enterprise is commercially licensed
  ([licensing](https://neo4j.com/licensing/), read 2026-08-07).

Read that as a decision rather than a feature table. If you pick that engine
*because* it will separate tenants into distinct databases with role-based access
control, and then deploy the free Community build, you get **one** database,
**no** roles, and **no** hot backup. The isolation you designed around does not
exist in what you shipped.

**And the failure is silent.** Queries work. The application behaves. Tests pass.
Nothing in normal operation reveals the gap. It surfaces in a security audit —
long after the schema and every query have been written around the assumption,
and long after changing course became expensive.

The check, in full:

1. Name the exact **edition, plan, and version** you will run in production. Not
   the product — the edition.
2. Open **that edition's own** feature matrix, from the vendor.
3. Confirm the specific property you are relying on is listed **for that
   edition**.
4. Do it **before** writing code.

This is not specific to graph databases. It applies to every engine in this
guide, and to managed services too, where the equivalent question is *which plan*:
compliance agreements, point-in-time restore windows, audit logging, and high
availability are routinely plan-gated. A vendor compliance page describing the
enterprise tier is not evidence about the tier in your shopping basket.

### Operational reality

**Who operates this at 3am?** A self-managed cluster is a reasonable choice for a
team with an on-call rota and an unreasonable one for a solo founder, regardless
of which is technically superior. Operational capacity is a hard constraint.

**Can you take a backup — and have you ever restored one?**

A backup nobody has restored is not a backup. It is an untested assumption with a
filename. The restore is the half that fails: wrong engine version, a missing
extension, an absent encryption key, an incomplete dump, a permissions model that
does not come back with the data.

The drill, which is a product requirement and not a nicety:

1. Take a real backup.
2. Restore it into a **fresh, empty** instance.
3. Point a running copy of the application at it.
4. Confirm the application works.
5. Write down the date and how long it took.
6. Repeat when the engine version or the backup tooling changes.

The advisor marks any recommendation **operationally incomplete** until this has
been done once. Managed backups do not exempt you — they make it more tempting to
skip, and the application cutover is still yours to rehearse.

### Exit cost

Exit cost is paid at the worst possible moment: during a price change, an
acquisition, an outage, or a compliance demand.

- **Low** — standard wire protocol, standard dump format, many interchangeable
  providers, self-hosting available as a floor. Postgres and SQLite.
- **Moderate** — the data leaves easily but a platform around it does not. You
  are rebuilding auth, generated APIs, storage, and functions.
- **High** — proprietary data model and API with no drop-in equivalent. Leaving
  means re-modelling the data and rewriting every access path.

If portability is a hard requirement, say so up front; it removes options before
you get attached to them.

---

## The candidates

Each entry below is summarised. **The "wrong for" list is the useful part** — a
pitch is easy to find elsewhere, an honest disqualification is not. Run
`--explain <id>` for the full entry including sources.

| Engine | Choose it when | It is wrong for |
|---|---|---|
| **PostgreSQL** (`postgres`) | Almost anything. The default, and usually correct. | Write volume beyond one primary; deep traversal over dense graphs; blobs in-table; workloads needing zero idle cost |
| **Postgres + pgvector** (`postgres_pgvector`) | Semantic search over data you already store relationally; filtered similarity search | Huge corpora with demanding recall at high concurrency; a product that is *only* vectors |
| **SQLite / embedded** (`sqlite`) | Device-local storage; single-node apps; app file formats; anything where "no server" is the win | Multiple machines writing; high write concurrency; in-database per-user access control |
| **Device-local / client-encrypted** (`device_local`) | One user's own data, no server-side computation; privacy as the product | Server-side search or analytics; sharing; account recovery; multi-device sync |
| **Neon** (`neon`) | Idle-dominated workloads; per-PR ephemeral databases via copy-on-write branching | Steady production traffic (the feature never fires); sparse *and* latency-sensitive paths; teams needing a whole platform |
| **Supabase** (`supabase`) | Client-heavy apps using the platform — generated API, auth, storage, functions — with RLS as the authorisation layer | Teams who want a database and nothing more; apps that already have a backend tier; idle paid projects |
| **Cloud SQL / RDS-class** (`cloud_sql`) | Steady production traffic inside that cloud; named support; broad compliance coverage | Idle or intermittent workloads (no autosuspend, never reaches zero); very small projects (no always-free tier) |
| **DynamoDB** (`dynamodb`) | Known, stable access patterns at very high scale; genuinely spiky traffic | Evolving or exploratory queries; analytics; items that grow (400 KB hard limit); small projects |
| **Firestore** (`firestore`) | Client-driven realtime and offline apps with no backend | Anything analytical (billed per document read); complex queries; intricate authorisation |
| **Redis / Valkey** (`redis_valkey`) | Cache, rate limiter, lock, queue, ephemeral session state | Being the system of record; datasets larger than memory; ad-hoc queries |
| **A real graph database** (`graph_db`) | Variable-depth traversal, dense connectivity, named graph algorithms | Sparse data; single-hop queries; no algorithms; **being chosen for an isolation property** |

### Cost traps worth knowing before you commit

These are the ones that surprise people, all from vendor documentation
(read 2026-08-07):

- **Firestore** bills per document read, and you are charged for documents *and
  index entries* read to satisfy a query. Counting and dashboard-style
  aggregation are precisely the operations this punishes.
  ([pricing](https://firebase.google.com/docs/firestore/pricing))
- **Firestore's** server client libraries **bypass security rules entirely**,
  authenticating via application default credentials instead. The boundary you
  tested from the client does not exist on the server path.
  ([rules](https://firebase.google.com/docs/firestore/security/get-started))
- **DynamoDB** secondary indexes consume write capacity *from the index*, so each
  one multiplies write cost — and in provisioned mode, an under-provisioned index
  throttles writes to the **base table**.
  ([GSI docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html))
- **Cloud SQL** has no autosuspend. Stopping an instance suspends instance
  charges, but storage and IP charges continue — it never reaches zero.
  ([docs](https://cloud.google.com/sql/docs/postgres/start-stop-restart-instance))
- **Neon** branches beyond the included count bill per branch-hour, and a child
  branch that falls outside the history window becomes as expensive as a root
  branch. ([pricing](https://neon.com/pricing))
- **Supabase** free projects pause after a week of inactivity; paid plans never
  pause, so an idle paid project pays in full.
  ([pricing](https://supabase.com/pricing))
- **pgvector** stores up to 16,000 dimensions but *indexes* only 2,000 on the
  `vector` type. The column accepts your embeddings and the index build fails —
  after the schema is written. ([pgvector](https://github.com/pgvector/pgvector))
- **Redis** persistence: the documentation itself says snapshotting is not very
  durable, the default append-only policy may lose a second of data, and you need
  both methods together for durability "comparable to what PostgreSQL can provide
  you".
  ([persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/))
- **Redis licensing** moved off BSD in 2024 (RSALv2/SSPLv1, from 7.4) and added
  AGPLv3 in 2025 (from Redis 8) — a tri-license, not a return to BSD. **Valkey**
  is the Linux Foundation's BSD fork from 7.2.4. They are wire-compatible, so be
  clear which one you actually ship.
  ([Redis 2024](https://redis.io/blog/redis-adopts-dual-source-available-licensing/),
  [Redis 2025](https://redis.io/blog/agplv3/),
  [Valkey](https://www.linuxfoundation.org/press/linux-foundation-launches-open-source-valkey-community))

Pricing and capabilities change. Every claim above carries its source and the
date it was read — **re-check before relying on one.** Where something is not
publicly documented, the catalog says so rather than guessing.

---

## How the advisor works

It is deliberately **not** a scoring quiz. There is no weighted total, because a
total hides the reason, and the reason is the product.

Instead it:

1. **Disqualifies** candidates with a stated rule and the answers that fired it,
   so you can read and argue with the logic.
2. **Argues both sides** — every recommendation carries its own case against. If
   a tool cannot say why its own answer might be wrong, it has not understood the
   decision well enough to give one.
3. **Emits verification tasks rather than assurances.** Two are unconditional:
   the edition check and the restore drill.
4. **Names what would change the answer**, tied to your specific answers, so the
   decision can be revisited on evidence rather than on vibes.
5. **Treats "I do not know" as a real answer** — reported back as a measurement
   task, never silently defaulted.

Its bias is toward boring. If nothing disqualifies a single relational database,
it says so plainly, because that is usually the right answer and pretending
otherwise would make the tool worse.

## Files

| Path | What it is |
|---|---|
| `tools/datastore_advisor/questions.json` | The elicitation axes, in deliberate order |
| `tools/datastore_advisor/catalog.json` | Candidate engines: fits, **wrong for**, edition traps, exit cost, sources |
| `tools/datastore_advisor/advisor.py` | The decision engine |
| `tools/datastore_advisor/cli.py` | Interview and rendering |
| `tools/datastore_advisor/selftest.py` | Offline self-test, no network |
| `docs/DATASTORE_DECISION.md` | The decision record you commit |

Adding an engine means adding a catalog entry — and the self-test will fail it if
it has no `wrong_for` list, which is the point.
