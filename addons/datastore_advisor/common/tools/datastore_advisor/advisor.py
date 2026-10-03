#!/usr/bin/env python3
"""Datastore advisor — turns elicited answers into a reasoned recommendation.

Deliberately *not* a scoring quiz. There is no weighted total and no single
verdict number, because a total hides the reason and the reason is the product.
Instead the engine does four things:

  1. **Disqualifies** candidates with a stated rule and the answers it fired on.
     A disqualification you can read and argue with is worth more than a score.
  2. **Argues both sides.** Every recommendation carries its own case against.
     If the tool cannot state why its own answer might be wrong, it has not
     understood the decision well enough to give one.
  3. **Emits verification tasks** rather than assurances. Two are unconditional:
     confirm the edition you will actually run has the feature you are choosing
     the engine for, and restore a backup before calling anything operational.
  4. **Names what would change the answer**, tied to the specific answers given,
     so the decision can be revisited on evidence instead of on vibes.

The user makes the call. This produces the argument, not the verdict.

Standard library only, Python 3.8+.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "catalog.json"
QUESTIONS_PATH = HERE / "questions.json"

UNKNOWN = "unknown"

# Scale bands at or below which a single well-indexed relational node is not a
# compromise. The advisor steers toward boring inside this range on purpose:
# buying distributed-systems complexity for a workload one node handles is the
# most common and most expensive mistake this tool exists to prevent.
SINGLE_NODE_SCALE = ("thousands", "hundreds_of_thousands", "millions")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    return load_json(path or CATALOG_PATH)


def load_questions(path: Optional[Path] = None) -> Dict[str, Any]:
    return load_json(path or QUESTIONS_PATH)


@dataclass
class Verification:
    """Something the user must go and check. Not advice — a task."""

    id: str
    title: str
    detail: str
    blocking: bool = False


@dataclass
class Recommendation:
    primary: str
    primary_name: str
    reasoning: List[str] = field(default_factory=list)
    case_against: List[str] = field(default_factory=list)
    alternatives: List[Tuple[str, str]] = field(default_factory=list)
    disqualified: List[Tuple[str, str]] = field(default_factory=list)
    supporting: List[Tuple[str, str]] = field(default_factory=list)
    verifications: List[Verification] = field(default_factory=list)
    what_would_change_this: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    operationally_ready: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary,
            "primary_name": self.primary_name,
            "reasoning": self.reasoning,
            "case_against": self.case_against,
            "alternatives": [{"engine": e, "note": n} for e, n in self.alternatives],
            "disqualified": [{"engine": e, "reason": r} for e, r in self.disqualified],
            "supporting": [{"engine": e, "note": n} for e, n in self.supporting],
            "verifications": [
                {"id": v.id, "title": v.title, "detail": v.detail, "blocking": v.blocking}
                for v in self.verifications
            ],
            "what_would_change_this": self.what_would_change_this,
            "unknowns": self.unknowns,
            "operationally_ready": self.operationally_ready,
        }


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _engine(catalog: Dict[str, Any], engine_id: str) -> Dict[str, Any]:
    for eng in catalog["engines"]:
        if eng["id"] == engine_id:
            return eng
    raise KeyError("unknown engine: " + engine_id)


def _name(catalog: Dict[str, Any], engine_id: str) -> str:
    return _engine(catalog, engine_id)["name"]


def graph_is_real(answers: Dict[str, Any]) -> Tuple[Optional[bool], List[str]]:
    """Decide whether a claimed graph workload is actually graph-shaped.

    Returns (verdict, evidence). A verdict of None means the user answered
    'unknown' on every axis that could settle it — which is not a licence to
    proceed, it is a measurement task.
    """
    density = answers.get("graph_edge_density", UNKNOWN)
    depth = answers.get("graph_traversal_depth", UNKNOWN)
    algos = answers.get("graph_algorithms", UNKNOWN)

    evidence: List[str] = []
    signals: List[bool] = []

    if density != UNKNOWN:
        dense = density in ("5_to_20", "over_20")
        signals.append(dense)
        evidence.append(
            "edge density is " + density.replace("_", " ")
            + (" per node, which is dense enough for traversal to pay"
               if dense else
               " per node, which is a foreign key rather than a graph")
        )
    if depth != UNKNOWN:
        deep = depth in ("deep_fixed", "variable")
        signals.append(deep)
        evidence.append(
            "deepest routine query is " + depth.replace("_", " ")
            + (", which is where index-free adjacency beats a relational plan"
               if deep else
               ", which a relational planner executes as a join")
        )
    if algos != UNKNOWN:
        has_algos = algos != "none"
        signals.append(has_algos)
        evidence.append(
            "named graph algorithms: " + ("yes" if has_algos else "none")
            + ("" if has_algos else ", so the traversal engine is never invoked")
        )

    if not signals:
        return None, evidence
    return any(signals), evidence


def _needs(answers: Dict[str, Any], shape: str) -> bool:
    return shape in _as_list(answers.get("workload_shape"))


def evaluate(answers: Dict[str, Any], catalog: Optional[Dict[str, Any]] = None) -> Recommendation:
    """Produce a reasoned recommendation from elicited answers."""
    cat = catalog or load_catalog()

    hold = answers.get("hold_data", UNKNOWN)
    scale = answers.get("scale", UNKNOWN)
    traffic = answers.get("traffic_profile", UNKNOWN)
    isolation = answers.get("isolation_model", UNKNOWN)
    iso_reason = answers.get("isolation_is_the_reason", UNKNOWN)
    regimes = _as_list(answers.get("regulated"))
    team = answers.get("team", UNKNOWN)
    backup = answers.get("backup_restore", UNKNOWN)
    exit_tol = answers.get("exit_tolerance", UNKNOWN)

    reasoning: List[str] = []
    disqualified: List[Tuple[str, str]] = []
    alternatives: List[Tuple[str, str]] = []
    supporting: List[Tuple[str, str]] = []
    verifications: List[Verification] = []
    changes: List[str] = []
    unknowns: List[str] = []

    # ---- Axis 0: should you hold this data at all? -----------------------
    prefer_local = False
    if hold == "must_not_hold":
        prefer_local = True
        reasoning.append(
            "You said holding this data readable is unacceptable, so the decision is "
            "already made: the operator stores ciphertext or nothing, and the remaining "
            "question is only what holds opaque blobs and sync state."
        )
    elif hold == "could_avoid":
        prefer_local = True
        reasoning.append(
            "You said this is really one user's own data. That makes device-local or "
            "client-encrypted storage a genuine candidate rather than a footnote: it "
            "removes an entire liability class instead of managing it. It is only the "
            "right answer if you never need the server to compute over the data — check "
            "the case against below before accepting it."
        )
    elif hold == UNKNOWN:
        unknowns.append(
            "Whether you need to hold this data at all is unresolved, and it is the "
            "one answer that changes every other answer. Settle it before writing code."
        )

    # A product that needs cross-user work cannot also hold nothing readable.
    if prefer_local and isolation in ("row_level", "schema_or_db", "instance"):
        verifications.append(
            Verification(
                id="local_vs_multitenant",
                title="Resolve the contradiction between 'do not hold it' and multi-tenancy",
                detail=(
                    "You described a multi-tenant isolation model *and* a preference for not "
                    "holding readable data. Those are usually incompatible: multi-tenancy "
                    "implies the server queries across users. Decide which is actually true "
                    "before choosing anything, because they lead to opposite architectures."
                ),
                blocking=True,
            )
        )

    # ---- Graph reality check --------------------------------------------
    graph_claimed = _needs(answers, "graph")
    graph_verdict: Optional[bool] = None
    if graph_claimed:
        graph_verdict, evidence = graph_is_real(answers)
        if graph_verdict is False:
            disqualified.append(
                (
                    "graph_db",
                    "You described the workload as graph-shaped, but the measurements say "
                    "otherwise: " + "; ".join(evidence) + ". That is a relational workload "
                    "with a join. A graph engine would carry a distinct query language, a "
                    "smaller hiring pool and a high exit cost for a traversal advantage you "
                    "never collect.",
                )
            )
            reasoning.append(
                "The graph reality check did not pass, so this is being treated as a "
                "relational workload. This is the most common expensive mistake in this "
                "decision and it is worth being blunt about."
            )
        elif graph_verdict is None:
            unknowns.append(
                "You claimed a graph workload but could not yet answer edge density, "
                "traversal depth, or which algorithms you will run. Measure those three "
                "before committing — they are the difference between a graph database and "
                "a foreign key, and they are cheap to measure and expensive to get wrong."
            )
            verifications.append(
                Verification(
                    id="measure_graph_shape",
                    title="Measure edge density, traversal depth, and named algorithms",
                    detail=(
                        "Count relationship rows, divide by entity rows. Write down the "
                        "deepest hop count any routine query needs. List the graph "
                        "algorithms by name. If density is around one or below, depth is "
                        "one or two, and the algorithm list is empty, you do not have a "
                        "graph workload."
                    ),
                    blocking=True,
                )
            )

    # ---- Exit cost ------------------------------------------------------
    if exit_tol == "critical":
        for eid in ("dynamodb", "firestore", "graph_db"):
            if eid in [d[0] for d in disqualified]:
                continue
            disqualified.append(
                (
                    eid,
                    "You said being able to leave is critical. "
                    + _engine(cat, eid)["exit_cost"],
                )
            )
        reasoning.append(
            "Portability is a stated hard requirement, so proprietary data models and "
            "APIs are out regardless of how well they fit the workload."
        )

    # ---- Scale ----------------------------------------------------------
    if scale in SINGLE_NODE_SCALE:
        reasoning.append(
            "At " + scale.replace("_", " ") + " of rows, a single well-indexed relational "
            "node is not a compromise — it is comfortably the right size. Distributed "
            "stores bought at this scale cost complexity every day and buy nothing back."
        )
        if scale == "thousands" and "dynamodb" not in [d[0] for d in disqualified]:
            disqualified.append(
                (
                    "dynamodb",
                    "At thousands of rows the single-table design discipline is pure "
                    "overhead. Its cost is only repaid at a scale this project does not "
                    "have and may never reach.",
                )
            )
    elif scale == "hundreds_of_millions":
        reasoning.append(
            "At hundreds of millions of rows the single-node assumption stops being "
            "automatic. Relational is still very likely right, but read replicas, "
            "partitioning, or sharding become part of the design rather than a later "
            "surprise."
        )
    elif scale == UNKNOWN:
        unknowns.append(
            "Scale is unmeasured. Until you know it, choose the option that is cheapest "
            "to leave — an unmeasured workload is not an argument for a bigger system, "
            "it is an argument for a portable one."
        )

    # ---- Traffic profile / scale-to-zero --------------------------------
    idle_dominated = traffic in ("mostly_idle", "spiky_unpredictable")
    if idle_dominated:
        reasoning.append(
            "Traffic is " + traffic.replace("_", " ") + ", which is the only condition "
            "under which scale-to-zero is worth real money. A provider that suspends idle "
            "compute is a genuine saving here rather than a marketing line."
        )
        alternatives.append(
            (
                "neon",
                "Worth pricing seriously because of the traffic profile: idle compute "
                "suspends. Weigh that against cold-start latency on the first request "
                "after an idle period — if this workload is both sparse and "
                "latency-sensitive, that is the worst combination and you should decide "
                "deliberately whether to keep compute warm.",
            )
        )
        if "cloud_sql" not in [d[0] for d in disqualified]:
            alternatives.append(
                (
                    "cloud_sql",
                    "Weaker fit for this traffic shape: provisioned capacity bills whether "
                    "or not anyone is using it, which is the most common source of "
                    "surprise cost on pre-launch and internal projects.",
                )
            )
    elif traffic == "steady":
        reasoning.append(
            "Traffic is steady, so scale-to-zero is inert for this workload — compute "
            "would never suspend. Judge serverless-Postgres providers on price, support, "
            "and branching instead, and do not pay a premium for a feature that will "
            "never fire."
        )
    elif traffic == UNKNOWN:
        unknowns.append(
            "Traffic shape is unknown, which is exactly the axis that decides whether "
            "scale-to-zero matters. Assume steady until measured; it is the safer default."
        )

    # ---- Team / operational reality -------------------------------------
    if team == "solo":
        reasoning.append(
            "A solo operator is a hard constraint on this decision, not a preference. "
            "Anything requiring cluster operations, capacity planning, or a specialist "
            "query language is a poor trade at this size regardless of technical merit."
        )
        if graph_verdict is not True and "graph_db" not in [d[0] for d in disqualified]:
            alternatives.append(
                (
                    "graph_db",
                    "Poor fit for a solo operator unless the workload genuinely demands "
                    "traversal: a distinct query language, thinner operational literature, "
                    "and a smaller pool of people who can help at 3am.",
                )
            )

    # ---- Regulatory ------------------------------------------------------
    real_regimes = [r for r in regimes if r != "none"]
    if real_regimes:
        verifications.append(
            Verification(
                id="compliance_on_the_plan_you_buy",
                title="Confirm the compliance agreement on the plan you will actually buy",
                detail=(
                    "You named these regimes: " + ", ".join(real_regimes) + ". Provider "
                    "compliance is usually tied to a specific plan or paid add-on rather "
                    "than being a property of the software. Open the provider's own "
                    "compliance page, find the plan you intend to pay for, and confirm the "
                    "agreement is available and signed before the first regulated record "
                    "is stored. A compliance page that describes the enterprise tier is "
                    "not evidence about the tier in your basket."
                ),
                blocking=True,
            )
        )
        if not prefer_local:
            supporting.append(
                (
                    "device_local",
                    "Worth a second look even if rejected: under a regulatory regime, the "
                    "cheapest data to protect is data you never hold. Ask whether any "
                    "portion of this dataset could stay on the user's device.",
                )
            )

    # ---- THE EDITION TRAP -------------------------------------------------
    # Unconditional, because it is the failure this tool exists to prevent. It
    # is escalated to blocking when an isolation or compliance property is part
    # of *why* an engine is being chosen.
    iso_blocking = iso_reason == "yes"
    verifications.append(
        Verification(
            id="edition_feature_check",
            title="Verify the edition you will actually run has the feature you are choosing it for",
            detail=(
                "Name the exact edition, plan, and version you will run in production — not "
                "the product, the edition. Open that edition's own feature matrix. Confirm "
                "the specific property you are relying on is listed for it.\n\n"
                "This matters because the properties teams most often select an engine for "
                "— separating data into distinct databases, role-based access control, "
                "fine-grained authorisation, online backup, audit logging, encryption at "
                "rest — are frequently gated to a paid or enterprise edition, while the "
                "edition that gets installed for evaluation and then quietly kept in "
                "production is the free or community one.\n\n"
                "The failure mode is silent. Nothing in normal operation reveals that the "
                "isolation you designed around does not exist in the build you deployed; it "
                "surfaces in a security audit, long after the schema and the queries have "
                "been written around the assumption. Five minutes with a feature matrix "
                "before writing code replaces a full audit afterwards."
                + (
                    "\n\nEscalated to blocking: you said an isolation, security, or "
                    "compliance property is part of why you are choosing this engine. That "
                    "is precisely the case where this check is not optional, and the "
                    "advisor will not confirm the choice on the strength of the engine's "
                    "name alone."
                    if iso_blocking
                    else ""
                )
            ),
            blocking=iso_blocking,
        )
    )
    if iso_blocking:
        reasoning.append(
            "You are choosing partly for an isolation or compliance property. That is the "
            "highest-risk part of this decision, so it is recorded as a blocking "
            "verification rather than accepted: confirm the property exists in the edition "
            "you will deploy, in that edition's own documentation."
        )
    if isolation == UNKNOWN:
        unknowns.append(
            "The isolation mechanism is unnamed. 'Customers are separate' is an intention; "
            "a row filter, a schema, a database, or a cluster is a mechanism. Name it."
        )

    # ---- THE RESTORE DRILL ------------------------------------------------
    restored = backup == "restored"
    verifications.append(
        Verification(
            id="restore_drill",
            title="Restore a backup into a working system, at least once",
            detail=(
                "A backup nobody has restored is not a backup; it is an untested assumption "
                "with a filename. The restore is the half that fails — wrong engine "
                "version, a missing extension, an absent encryption key, an incomplete "
                "dump, or a permissions model that does not come back with the data.\n\n"
                "The drill: take a real backup, restore it into a fresh empty instance, "
                "point a running copy of the application at it, and confirm the application "
                "works. Write down the date and how long it took. Repeat when the engine "
                "version or the backup tooling changes."
                + (
                    ""
                    if restored
                    else "\n\nThis recommendation is marked operationally incomplete until "
                    "this has been done once. That is not pedantry: an untested restore is "
                    "the most common reason a recoverable incident becomes a fatal one."
                )
            ),
            blocking=not restored,
        )
    )
    if backup == "provider_default":
        reasoning.append(
            "You are relying on the provider's default backups. Managed backups are real, "
            "but they make it especially tempting never to test a restore — and the restore "
            "is still yours to perform, including the application cutover."
        )

    # ---- Choose the primary ---------------------------------------------
    disqualified_ids = [d[0] for d in disqualified]

    if prefer_local:
        primary = "device_local"
    elif graph_claimed and graph_verdict is True:
        primary = "graph_db"
    elif _needs(answers, "vector"):
        primary = "postgres_pgvector"
    elif (
        team in ("solo", "small_team")
        and scale in ("thousands", "hundreds_of_thousands")
        and isolation == "single_tenant"
        and not _needs(answers, "blob")
    ):
        primary = "sqlite"
    else:
        primary = "postgres"

    if primary in disqualified_ids:
        primary = "postgres"

    # ---- Reasoning for the default --------------------------------------
    if primary in ("postgres", "postgres_pgvector"):
        reasoning.append(
            "The recommendation is relational because nothing in your answers disqualified "
            "it, and that is usually how this decision should end. A single Postgres "
            "instance covers relational, document, key-value, full-text, geospatial and — "
            "with an extension — vector search, behind one backup and one transaction "
            "boundary. Reaching for something else should require a reason this exercise "
            "did not produce."
        )
        if _needs(answers, "vector"):
            reasoning.append(
                "Vector search is in scope, and keeping embeddings beside the rows they "
                "describe means filtered similarity search is a WHERE clause rather than "
                "two systems kept in sync."
            )
    elif primary == "sqlite":
        reasoning.append(
            "An embedded database is the recommendation because the workload is "
            "single-tenant, modest, and operated by a small team: no server, no connection "
            "pool, no network, and a restore drill that is genuinely a file copy. Its hard "
            "limit is multiple machines writing concurrently — if that is on the roadmap, "
            "start with Postgres instead."
        )
    elif primary == "device_local":
        reasoning.append(
            "Device-local or client-encrypted storage is the recommendation because you "
            "indicated the server does not need to read this data. Confirm the property "
            "end to end before claiming it — logs, crash reports, analytics payloads and "
            "backups are where plaintext leaks out of an otherwise sound design."
        )
    elif primary == "graph_db":
        reasoning.append(
            "A graph engine is the recommendation because the reality check passed on the "
            "measurements you gave, not on the domain vocabulary. Read the edition "
            "verification above carefully — this family is where the edition gap is most "
            "expensive."
        )

    # ---- Supporting components ------------------------------------------
    if _needs(answers, "blob"):
        supporting.append(
            (
                "postgres",
                "Large files do not belong in the database. Put blobs in object storage and "
                "keep a URL and metadata in the row — otherwise every backup and every "
                "restore carries the media, which is how a five-minute restore becomes a "
                "five-hour one.",
            )
        )
    supporting.append(
        (
            "redis_valkey",
            "A cache, not a store. Add it when you have measured a problem it solves; "
            "adding it earlier buys an invalidation bug and a second failure domain. If "
            "removing it would break correctness rather than speed, it has quietly become "
            "a system of record and needs to be treated as one.",
        )
    )

    # ---- The case against the primary -----------------------------------
    prim = _engine(cat, primary)
    case_against = list(prim["wrong_for"][:3])
    if primary in ("postgres", "postgres_pgvector") and idle_dominated:
        case_against.append(
            "For your traffic shape specifically: plain managed Postgres bills while idle. "
            "If cost matters more than provider familiarity, a provider that suspends idle "
            "compute is the better trade, and this recommendation is the conservative one "
            "rather than the cheapest one."
        )
    if primary == "postgres" and scale == "hundreds_of_millions":
        case_against.append(
            "At your stated scale the write path deserves scrutiny before committing: a "
            "single primary absorbs a great deal, but not everything, and discovering the "
            "ceiling in production is expensive."
        )

    # ---- Alternatives worth pricing --------------------------------------
    if primary != "sqlite" and isolation == "single_tenant" and scale in SINGLE_NODE_SCALE:
        alternatives.append(
            (
                "sqlite",
                "Genuinely viable given single-tenant data at this scale, and it removes "
                "the server entirely. Rejected only if you need several machines writing "
                "concurrently, or database-enforced per-user access control.",
            )
        )
    if primary in ("postgres", "postgres_pgvector") and not idle_dominated and traffic != UNKNOWN:
        alternatives.append(
            (
                "supabase",
                "Worth considering only if you will use the platform around the database — "
                "generated API, hosted auth, storage, functions. If you want a database and "
                "nothing more, the platform is coupling you would be paying for and later "
                "unpicking.",
            )
        )

    # ---- What would change this answer ------------------------------------
    if scale in SINGLE_NODE_SCALE:
        changes.append(
            "Write volume exceeding what one primary absorbs, or the biggest table passing "
            "hundreds of millions of rows. That is the threshold where the single-node "
            "default stops being automatic — not before it."
        )
    if traffic == "steady":
        changes.append(
            "The traffic profile becoming idle-dominated — this turning into an internal "
            "tool, a seasonal product, or a per-developer environment. Scale-to-zero goes "
            "from inert to worth real money at that point."
        )
    if idle_dominated:
        changes.append(
            "Traffic becoming steady, which makes scale-to-zero inert and turns the "
            "comparison back into ordinary price and support."
        )
    if graph_verdict is False:
        changes.append(
            "Edge density rising past roughly five per node, routine queries needing "
            "variable-depth traversal, or a named graph algorithm entering the roadmap. "
            "Any one of those would reopen the graph question honestly."
        )
    if primary == "device_local":
        changes.append(
            "A requirement for server-side search, aggregation, moderation, cross-user "
            "sharing, or account recovery. Any of these gives back the property that "
            "justified holding nothing, and the architecture should change with it."
        )
    if primary == "sqlite":
        changes.append(
            "A second application server needing to write. That is the hard boundary, and "
            "no configuration works around it."
        )
    if not real_regimes:
        changes.append(
            "Entering a regulatory regime, which constrains the provider list before it "
            "constrains the engine."
        )
    changes.append(
        "Discovering during the edition check that the feature you are relying on is not in "
        "the edition you planned to run. That invalidates the choice outright rather than "
        "adjusting it."
    )

    rec = Recommendation(
        primary=primary,
        primary_name=_name(cat, primary),
        reasoning=reasoning,
        case_against=case_against,
        alternatives=alternatives,
        disqualified=disqualified,
        supporting=supporting,
        verifications=verifications,
        what_would_change_this=changes,
        unknowns=unknowns,
        operationally_ready=restored and not any(v.blocking for v in verifications),
    )
    return rec


def _bullets(items: Sequence[str], prefix: str = "- ") -> str:
    return "\n".join(prefix + i for i in items) if items else "_(none)_"


def render_markdown(rec: Recommendation, answers: Dict[str, Any],
                    catalog: Optional[Dict[str, Any]] = None) -> str:
    """Render the decision record that gets committed alongside the code."""
    cat = catalog or load_catalog()
    out: List[str] = []
    out.append("# Datastore decision record")
    out.append("")
    out.append(
        "Generated by the datastore advisor. This is an argument, not a verdict — "
        "the decision is yours, and the reasoning below is what you are agreeing or "
        "disagreeing with. Commit this file and revise it when one of the triggers at "
        "the bottom fires."
    )
    out.append("")
    out.append("## Recommendation: " + rec.primary_name)
    out.append("")
    out.append("**Operationally ready:** " + ("yes" if rec.operationally_ready else
               "**no** — blocking verifications are outstanding (see below)"))
    out.append("")
    out.append("### Why")
    out.append("")
    out.append(_bullets(rec.reasoning))
    out.append("")
    out.append("### The case against this recommendation")
    out.append("")
    out.append(
        "Stated deliberately. If none of these worry you, either the fit is genuinely "
        "good or the answers above were optimistic."
    )
    out.append("")
    out.append(_bullets(rec.case_against))
    out.append("")

    if rec.disqualified:
        out.append("### Ruled out, and why")
        out.append("")
        for eid, reason in rec.disqualified:
            out.append("- **" + _name(cat, eid) + "** — " + reason)
        out.append("")

    if rec.alternatives:
        out.append("### Alternatives worth pricing before you commit")
        out.append("")
        for eid, note in rec.alternatives:
            out.append("- **" + _name(cat, eid) + "** — " + note)
        out.append("")

    if rec.supporting:
        out.append("### Supporting components")
        out.append("")
        for eid, note in rec.supporting:
            out.append("- **" + _name(cat, eid) + "** — " + note)
        out.append("")

    out.append("### Verify before you build")
    out.append("")
    for v in rec.verifications:
        marker = "**[BLOCKING]** " if v.blocking else ""
        out.append("#### " + marker + v.title)
        out.append("")
        out.append(v.detail)
        out.append("")

    if rec.unknowns:
        out.append("### What you do not know yet")
        out.append("")
        out.append(
            "Answered 'unknown'. These are measurement tasks, not blockers to thinking — "
            "but an unmeasured axis is an argument for the most portable option, never "
            "for the biggest one."
        )
        out.append("")
        out.append(_bullets(rec.unknowns))
        out.append("")

    out.append("### What would change this answer")
    out.append("")
    out.append(_bullets(rec.what_would_change_this))
    out.append("")

    out.append("### Answers this was based on")
    out.append("")
    for key in sorted(answers):
        val = answers[key]
        shown = ", ".join(_as_list(val)) if isinstance(val, (list, tuple)) else str(val)
        out.append("- `" + key + "`: " + shown)
    out.append("")

    cites = _engine(cat, rec.primary).get("citations", [])
    if cites:
        out.append("### Sources for capability claims about the recommendation")
        out.append("")
        for c in cites:
            out.append("- " + c["claim"] + " — <" + c["url"] + "> (read " + c["accessed"] + ")")
        out.append("")
        out.append(
            "_Capability and pricing details move. Re-check these before relying on one._"
        )
        out.append("")

    return "\n".join(out)
