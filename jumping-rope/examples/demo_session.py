"""Scripted 30-turn fake session demonstrating the jumping-rope lifecycle:

rope evolution → budget-driven demotion → jumps → cache-miss retrieval.

Run:  python examples/demo_session.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.tokens import count_tokens

TURNS = [
    # (section, content, kwargs)
    ("state", "/srv/checkout-service", {"key": "cwd"}),
    ("state", "feat/idempotent-payments", {"key": "branch"}),
    ("goal", "make the payment endpoint idempotent", {"status": "active"}),
    ("goal", "add replay-safe webhook handling", {"status": "pending"}),
    ("decision", "we decided to use an idempotency-key header because the client "
                 "already sends one and it avoids a schema migration", {"reason": "no migration"}),
    ("delta", "added IdempotencyKey middleware with a 24h ttl cache",
     {"path": "src/middleware/idempotency.py"}),
    ("open", "the redis eviction policy is still unconfirmed for the ttl cache",
     {"priority": 1}),
    ("decision", "we decided to use redis SETNX because it is atomic and the "
                 "cluster already exists in every environment", {"reason": "atomic, no new infra"}),
    ("delta", "wired middleware into the payments router", {"path": "src/routes/payments.py"}),
    ("open", "duplicate submissions from the mobile app retry loop", {"priority": 0}),
    ("decision", "the webhook consumer will replay from the kafka topic "
                 "billing-events because the vendor cannot re-send", {"reason": "vendor limit"}),
    ("delta", "consumer group checkpoint every 500 messages", {"path": "src/consumers/billing.py"}),
    ("open", "should the ttl be configurable per merchant?", {"priority": 3}),
    ("decision", "we decided to use a dead letter queue for poison webhook "
                 "payloads because silent drops hide vendor bugs", {"reason": "observability"}),
    ("delta", "dead letter queue with 3 retries and exponential backoff",
     {"path": "src/consumers/dlq.py"}),
    ("open", "load test the SETNX path at 2000 rps", {"priority": 2}),
    ("decision", "canary deploy at five percent of traffic because the blast "
                 "radius of double-charging is unacceptable", {"reason": "blast radius"}),
    ("delta", "canary manifest with automatic rollback on error budget burn",
     {"path": "deploy/canary.yaml"}),
    ("open", "the finance team wants a reconciliation report", {"priority": 2}),
    ("decision", "reconciliation report is a nightly batch job not a live "
                 "dashboard because finance reviews once a day", {"reason": "matches cadence"}),
    ("delta", "nightly reconciliation job comparing charges to ledger entries",
     {"path": "src/jobs/reconcile.py"}),
    ("open", "ledger entries lag charges by up to four minutes", {"priority": 1}),
    ("decision", "the reconciliation window is offset by ten minutes because "
                 "of the observed ledger lag", {"reason": "observed lag"}),
    ("delta", "added lag-aware window offset to the reconcile job",
     {"path": "src/jobs/reconcile.py"}),
    ("open", "alert threshold for reconciliation mismatches", {"priority": 3}),
    ("decision", "mismatch alerts page only above 0.1 percent because "
                 "historical noise sits near 0.02 percent", {"reason": "noise floor"}),
    ("delta", "pagerduty alert wired to the mismatch metric", {"path": "deploy/alerts.yaml"}),
    ("open", "runbook for the double-charge incident path", {"priority": 2}),
    ("decision", "the runbook lives in the repo not the wiki because the wiki "
                 "rots and the repo is versioned", {"reason": "wiki rots"}),
    ("delta", "incident runbook added", {"path": "docs/runbooks/double-charge.md"}),
]


def main() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="jrope-demo-"))
    session = JumpingRopeSession(
        data_dir,
        session_id="demo",
        config=JumpConfig(
            rope_budget_tokens=500,  # tight budget so demotion is visible
            jump_threshold_tokens=900,  # aggressive for demo purposes
            jump_every_n_turns=8,
        ),
        clock=lambda: "2026-07-03T12:00:00Z",
    )
    print(f"backend: {session.store.stats()['backend']}")

    jumps = 0
    for turn, (section, content, kwargs) in enumerate(TURNS, start=1):
        session.record_event(section, content, **kwargs)
        session.note_turn(f"turn {turn}: {content}")
        rope_tokens = count_tokens(session.rope.render())
        line = (
            f"turn {turn:>2} | {section:<8} | rope={rope_tokens:>4} tok "
            f"| live≈{session.meta.live_context_tokens:>5} tok "
            f"| keys={len(session.rope.keys)}"
        )
        if session.should_jump():
            context = session.jump()
            jumps += 1
            line += f"  ← JUMP #{jumps} (carried context: {count_tokens(context)} tok)"
        print(line)

    print("\n=== final jump: the rope below is the ENTIRE carried context ===\n")
    final = session.jump()
    jumps += 1
    print(final)
    final_tokens = count_tokens(final)
    print(f"=== jumps: {jumps} | final rope: {final_tokens} tokens "
          f"(budget 500) ===")
    assert jumps >= 3, "demo must show at least 3 jumps"
    assert final_tokens <= 500, "final rope must fit the budget"

    print("\n=== cache-miss retrieval of a demoted fact ===\n")
    result = session.retrieve("why did we choose redis SETNX for idempotency", k=2)
    print(result)
    assert "SETNX" in result, "demoted decision must be retrievable"
    print("\nretrieval OK — demoted decision recovered from TurboVec")

    session.close()
    shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
