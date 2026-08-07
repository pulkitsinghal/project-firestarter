#!/usr/bin/env python3
"""Offline self-test for the datastore advisor. No network, no dependencies.

Run:  python3 tools/datastore_advisor/selftest.py

Asserts the behaviours that make this an advisor rather than a quiz:
  * the default answer is boring, and stays boring for ordinary workloads;
  * a claimed graph workload that measures sparse and shallow is disqualified,
    with the numbers echoed back;
  * the edition check and the restore drill are emitted unconditionally, and
    escalate to blocking in the cases that warrant it;
  * every recommendation carries a case against itself and a set of falsifiers;
  * every catalog entry has a `wrong_for` list, because a catalog of pitches
    would be worse than no catalog at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from .advisor import UNKNOWN, evaluate, load_catalog, load_questions, render_markdown
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from advisor import (  # type: ignore[no-redef]
        UNKNOWN,
        evaluate,
        load_catalog,
        load_questions,
        render_markdown,
    )

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print("  ok   " + label)
    else:
        print("  FAIL " + label + ("  -- " + detail if detail else ""))
        FAILURES.append(label)


def _ids(pairs):
    return [p[0] for p in pairs]


def _verif(rec, vid):
    for v in rec.verifications:
        if v.id == vid:
            return v
    return None


def test_catalog_integrity():
    print("\ncatalog integrity")
    cat = load_catalog()
    ids = [e["id"] for e in cat["engines"]]
    check("catalog is non-empty", len(ids) >= 10, str(len(ids)) + " engines")
    check("engine ids are unique", len(ids) == len(set(ids)))
    for eng in cat["engines"]:
        check(
            eng["id"] + " states what it is wrong for",
            bool(eng.get("wrong_for")),
            "a catalog of pitches is worse than none",
        )
        check(eng["id"] + " states an exit cost", bool(eng.get("exit_cost")))
        for c in eng.get("citations") or []:
            check(
                eng["id"] + " citation has url+date+claim",
                bool(c.get("url")) and bool(c.get("accessed")) and bool(c.get("claim")),
            )
    required = {
        "postgres", "postgres_pgvector", "sqlite", "neon", "supabase",
        "cloud_sql", "dynamodb", "firestore", "redis_valkey", "graph_db",
        "device_local",
    }
    check("covers every required family", required.issubset(set(ids)),
          "missing: " + ", ".join(sorted(required - set(ids))))


def test_questions_integrity():
    print("\nquestion set integrity")
    q = load_questions()
    axes = q["axes"]
    ids = [a["id"] for a in axes]
    check("axis ids are unique", len(ids) == len(set(ids)))
    check("every axis explains why it matters", all(a.get("why_it_matters") for a in axes))
    first = sorted(axes, key=lambda a: a["order"])[0]
    check(
        "the first question asked is whether to hold the data at all",
        first["id"] == "hold_data",
        "got " + first["id"],
    )
    graph_axes = [a for a in axes if a.get("asked_when", {}).get("workload_shape")]
    check("graph claims trigger follow-up questions", len(graph_axes) >= 3)


def test_default_is_boring():
    print("\nthe default answer is boring")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["relational"],
        "scale": "hundreds_of_thousands",
        "traffic_profile": "steady",
        "isolation_model": "row_level",
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "small_team",
        "backup_restore": "restored",
        "exit_tolerance": "prefer",
    })
    check("recommends plain Postgres", rec.primary == "postgres", rec.primary)
    check("says scale-to-zero is inert for steady traffic",
          any("inert" in r for r in rec.reasoning))
    check("still argues against itself", len(rec.case_against) >= 3)
    check("names falsifiers", len(rec.what_would_change_this) >= 2)


def test_sparse_graph_is_disqualified():
    print("\na sparse, shallow 'graph' is called what it is")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["graph"],
        "graph_edge_density": "under_1",
        "graph_traversal_depth": "one_hop",
        "graph_algorithms": "none",
        "scale": "thousands",
        "traffic_profile": "mostly_idle",
        "isolation_model": "row_level",
        "isolation_is_the_reason": "yes",
        "regulated": ["none"],
        "team": "solo",
        "backup_restore": "none",
        "exit_tolerance": "prefer",
    })
    check("graph database is disqualified", "graph_db" in _ids(rec.disqualified))
    reason = dict(rec.disqualified).get("graph_db", "")
    check("the disqualification echoes the measurements",
          "edge density" in reason and "algorithms" in reason)
    check("falls back to relational", rec.primary == "postgres", rec.primary)
    check("offers scale-to-zero as a real alternative for idle traffic",
          "neon" in _ids(rec.alternatives))
    ed = _verif(rec, "edition_feature_check")
    check("edition check is blocking when isolation drove the choice",
          ed is not None and ed.blocking)
    check("not operationally ready without a restore drill",
          rec.operationally_ready is False)


def test_real_graph_survives():
    print("\na genuinely graph-shaped workload is not talked out of it")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["graph"],
        "graph_edge_density": "over_20",
        "graph_traversal_depth": "variable",
        "graph_algorithms": "analytics",
        "scale": "millions",
        "traffic_profile": "steady",
        "isolation_model": "single_tenant",
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "has_ops",
        "backup_restore": "restored",
        "exit_tolerance": "dont_care",
    })
    check("recommends a graph database", rec.primary == "graph_db", rec.primary)
    check("graph database is not disqualified", "graph_db" not in _ids(rec.disqualified))
    check("still warns about the edition gap", _verif(rec, "edition_feature_check") is not None)
    check("still argues against itself", len(rec.case_against) >= 3)


def test_unknown_graph_is_a_measurement_task():
    print("\n'I do not know' on the graph axes becomes a measurement task")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["graph"],
        "graph_edge_density": UNKNOWN,
        "graph_traversal_depth": UNKNOWN,
        "graph_algorithms": UNKNOWN,
        "scale": UNKNOWN,
        "traffic_profile": UNKNOWN,
        "isolation_model": UNKNOWN,
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "solo",
        "backup_restore": "backup_only",
        "exit_tolerance": "prefer",
    })
    check("does not disqualify on absent evidence", "graph_db" not in _ids(rec.disqualified))
    check("does not silently recommend a graph database", rec.primary != "graph_db")
    check("emits a measurement verification", _verif(rec, "measure_graph_shape") is not None)
    check("records the unknowns", len(rec.unknowns) >= 3)


def test_hold_nothing_is_first_class():
    print("\n'do you even want to hold it' actually changes the answer")
    rec = evaluate({
        "hold_data": "could_avoid",
        "workload_shape": ["document"],
        "scale": "thousands",
        "traffic_profile": "mostly_idle",
        "isolation_model": "single_tenant",
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "solo",
        "backup_restore": "restored",
        "exit_tolerance": "prefer",
    })
    check("recommends device-local / client-encrypted", rec.primary == "device_local", rec.primary)
    check("names account recovery as the cost",
          any("recovery" in c.lower() for c in rec.case_against))
    check("names what would give the property back",
          any("server-side" in c for c in rec.what_would_change_this))

    clash = evaluate({
        "hold_data": "must_not_hold",
        "workload_shape": ["relational"],
        "isolation_model": "row_level",
        "isolation_is_the_reason": "no",
        "team": "solo",
        "backup_restore": "restored",
    })
    check("flags 'hold nothing' against a multi-tenant model",
          _verif(clash, "local_vs_multitenant") is not None)


def test_exit_cost_is_enforced():
    print("\nportability as a hard requirement removes proprietary stores")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["key_value"],
        "scale": "hundreds_of_millions",
        "traffic_profile": "spiky_unpredictable",
        "isolation_model": "row_level",
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "has_ops",
        "backup_restore": "restored",
        "exit_tolerance": "critical",
    })
    for eid in ("dynamodb", "firestore", "graph_db"):
        check(eid + " ruled out on exit cost", eid in _ids(rec.disqualified))


def test_regulated_forces_plan_check():
    print("\na regulatory regime forces a plan-level compliance check")
    rec = evaluate({
        "hold_data": "must_hold",
        "workload_shape": ["relational"],
        "scale": "millions",
        "traffic_profile": "steady",
        "isolation_model": "schema_or_db",
        "isolation_is_the_reason": "yes",
        "regulated": ["privacy", "residency"],
        "team": "small_team",
        "backup_restore": "restored",
        "exit_tolerance": "prefer",
    })
    v = _verif(rec, "compliance_on_the_plan_you_buy")
    check("emits a compliance verification", v is not None and v.blocking)
    check("names the regimes given", v is not None and "residency" in v.detail)


def test_unconditional_verifications():
    print("\nthe two unconditional checks are always emitted")
    rec = evaluate({"hold_data": UNKNOWN, "team": "solo", "backup_restore": "restored"})
    check("edition check present", _verif(rec, "edition_feature_check") is not None)
    check("restore drill present", _verif(rec, "restore_drill") is not None)
    ed = _verif(rec, "edition_feature_check")
    check("edition check explains the silent-failure mode",
          ed is not None and "silent" in ed.detail.lower())

    never = evaluate({"hold_data": "must_hold", "team": "solo", "backup_restore": "provider_default"})
    rd = _verif(never, "restore_drill")
    check("restore drill blocks when never restored", rd is not None and rd.blocking)
    check("untested restore blocks operational readiness",
          never.operationally_ready is False)


def test_render_is_complete():
    print("\nthe rendered record contains the argument, not just the answer")
    answers = {
        "hold_data": "must_hold",
        "workload_shape": ["relational", "vector"],
        "scale": "millions",
        "traffic_profile": "mostly_idle",
        "isolation_model": "row_level",
        "isolation_is_the_reason": "no",
        "regulated": ["none"],
        "team": "small_team",
        "backup_restore": "restored",
        "exit_tolerance": "prefer",
    }
    rec = evaluate(answers)
    doc = render_markdown(rec, answers)
    check("recommends pgvector for a vector workload",
          rec.primary == "postgres_pgvector", rec.primary)
    for heading in (
        "## Recommendation",
        "### Why",
        "### The case against this recommendation",
        "### Verify before you build",
        "### What would change this answer",
        "### Answers this was based on",
    ):
        check("record contains '" + heading + "'", heading in doc)
    check("record cites sources for the recommendation", "read 2026-" in doc)
    check("record is substantial", len(doc) > 2500, str(len(doc)) + " chars")


def main():
    print("datastore advisor self-test (offline)")
    test_catalog_integrity()
    test_questions_integrity()
    test_default_is_boring()
    test_sparse_graph_is_disqualified()
    test_real_graph_survives()
    test_unknown_graph_is_a_measurement_task()
    test_hold_nothing_is_first_class()
    test_exit_cost_is_enforced()
    test_regulated_forces_plan_check()
    test_unconditional_verifications()
    test_render_is_complete()

    print("")
    if FAILURES:
        print(str(len(FAILURES)) + " check(s) failed:")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
