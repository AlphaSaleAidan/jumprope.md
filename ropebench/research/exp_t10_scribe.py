"""T10 — scribe fidelity: does a LIVE model actually capture facts to the rope?

Every prior result in this repo assumes PERFECT CAPTURE: the scenario
generator tells the harness which events are rope-worthy and the harness
applies them mechanically (RopeRegime._record). In production nobody does
that — a live model must NOTICE that a fact is durable and log it before the
transcript dies. The whole system is a chain:

    end-to-end retention = capture x carry x recall (x use)

Phases 1-5 proved carry + recall (+ mostly use). T10 measures the missing
first factor. If capture is weak, every downstream number is an upper bound
on a system nobody runs; if capture is strong, the chain closes.

Protocol (per seed):
  1. Generate a CHATTY scenario (facts wrapped in conversational filler +
     routine-churn noise every turn) — the capture problem at its realistic
     hardest for a synthetic stream.
  2. Three conditions over the same stream:
       scribe-rope — a live model sees each turn's raw transcript + current
                     rope, and emits ledger ops (JSON lines) or NONE. Ops are
                     applied through the same JumpingRopeSession as the
                     mechanical regime. Capture decided by the model.
       mech-rope   — RopeRegime: generator-directed capture (upper bound).
       summary     — SummaryRegime: what every tool ships (baseline).
  3. All probes answered by the SAME deterministic ScriptedModel, so the
     reader is a constant and any delta between scribe-rope and mech-rope is
     capture (plus rope-pollution) alone.
  4. Metrics:
       capture_rate — at probe time, is the expected value present verbatim
                      anywhere in rope render OR retrievable from the vault?
       end-to-end accuracy per condition
       loss decomposition — each scribe-rope miss is a CAPTURE loss (value
                      never made it in) or a RECALL loss (in, but the reader
                      couldn't surface it)
       noise ops    — ops emitted for filler churn (over-logging pollutes
                      the rope and evicts real facts sooner)

A --scribe perfect mode replays the generator's own mapping through the
scribe plumbing (free, no model): it must reproduce mech-rope within noise,
validating the harness before any paid call.

Run (from ropebench/):
  python research/exp_t10_scribe.py --scribe perfect            # harness check
  JROPE_BENCH_BUDGET_USD=1 python research/exp_t10_scribe.py \
      --scribe cmd --cmd "claude -p --model haiku"              # live
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from jumping_rope import JumpConfig, JumpingRopeSession
from jumping_rope.tokens import count_tokens

from ropebench.models import ScriptedModel
from ropebench.pricing import enforce_budget, estimate_cost
from ropebench.regimes import RopeRegime, SummaryRegime
from ropebench.scenario import Event, Probe, Scenario, generate

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "t10-scribe"

SCRIBE_PROMPT = """\
You are the SCRIBE for a long agent session. You maintain the session ledger
(the rope). The transcript is disposable — anything you do not log is LOST
forever at the next context clear. Anything you log survives.

Given ONE turn of raw transcript, decide what is durable and emit ledger ops.

Rules:
- Log durable facts (pins, versions, builds, configs), decisions (with the
  reason), new goals, and goal completions.
- Copy identifiers EXACTLY as written (build ids, names, numbers). Never
  paraphrase an identifier.
- SKIP routine churn: renames, tidying, reindenting, linting, reordering,
  annotation passes, greetings, filler chatter. Logging noise evicts real
  facts from the ledger.
- Output ONE JSON object per line, nothing else. If nothing in the turn is
  durable, output exactly: NONE

Ops (choose the best-fitting one per item):
{"op": "fact", "text": "<the durable fact, identifiers verbatim>"}
{"op": "decision", "text": "<what was decided>", "reason": "<why>"}
{"op": "goal", "text": "<the new goal>"}
{"op": "goal_done", "text": "<which goal is now done>"}

CURRENT LEDGER (for context — do not repeat items already on it):
%(rope)s

TURN TRANSCRIPT:
%(turn)s

Ops:"""


# --------------------------------------------------------------- scribes


class PerfectScribe:
    """Replays the generator's own event mapping through the scribe pipe —
    validates the plumbing; must match mech-rope within noise."""

    name = "perfect"
    calls = 0

    def ops_for_turn(self, events: list[Event], rope_render: str) -> list[dict]:
        ops = []
        for e in events:
            if e.kind == "fact":
                ops.append({"op": "fact", "text": e.text})
            elif e.kind == "decision":
                ops.append({"op": "decision", "text": e.text,
                            "reason": str(e.rope_kwargs.get("reason", ""))})
            elif e.kind == "goal":
                ops.append({"op": "goal", "text": e.text})
            elif e.kind == "goal_done":
                ops.append({"op": "goal_done", "text": e.text})
            # filler: a perfect scribe logs nothing
        return ops


class CommandScribe:
    """Live scribe via a CLI model (`claude -p --model haiku`). Failed or
    unparseable output means NOTHING is logged that turn — a real, scored
    outcome (that is exactly how a lazy scribe loses facts)."""

    name = "command"

    def __init__(self, argv: list[str], timeout_s: int = 120) -> None:
        self.argv = argv
        self.timeout_s = timeout_s
        self.calls = 0
        self.parse_failures = 0

    def ops_for_turn(self, events: list[Event], rope_render: str) -> list[dict]:
        turn_text = " ".join(e.text for e in events)
        prompt = SCRIBE_PROMPT % {"rope": rope_render or "(empty)",
                                  "turn": turn_text}
        self.calls += 1
        try:
            proc = subprocess.run(self.argv, input=prompt, capture_output=True,
                                  text=True, timeout=self.timeout_s, check=False)
            raw = proc.stdout.strip()
        except subprocess.TimeoutExpired:
            raw = ""
        ops: list[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.upper() == "NONE" or line.startswith(("```", "#")):
                continue  # fences and prose are wrapper noise, not lost ops
            line = line.strip("`")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                self.parse_failures += 1
                continue
            if isinstance(obj, dict) and obj.get("op") and obj.get("text"):
                ops.append(obj)
        return ops


# --------------------------------------------------- scribe-driven rope


class ScribeRope:
    """Same JumpingRopeSession as RopeRegime — but the SCRIBE decides what
    gets recorded. fact→delta(alternating open) is not replicated; the scribe
    op 'fact' lands as an OPEN item (P2), which the budget treats the same."""

    name = "scribe-rope"

    def __init__(self, scribe, rope_budget_tokens: int = 600,
                 jump_every_n_turns: int = 8) -> None:
        self.scribe = scribe
        self._dir = Path(tempfile.mkdtemp(prefix="t10-scribe-"))
        self.session = JumpingRopeSession(
            self._dir, session_id="t10",
            config=JumpConfig(rope_budget_tokens=rope_budget_tokens,
                              jump_threshold_tokens=rope_budget_tokens * 3,
                              jump_every_n_turns=jump_every_n_turns),
            force_fallback=True, clock=lambda: "2026-07-06T00:00:00Z",
        )
        self.ops_total = 0
        self.noise_ops = 0  # ops emitted on turns whose only events are filler
        self.turn_tokens: list[int] = []

    def observe(self, turn: int, events: list[Event]) -> None:
        ops = self.scribe.ops_for_turn(events, self.session.rope.render())
        filler_only = all(e.kind == "filler" for e in events)
        self.ops_total += len(ops)
        if filler_only:
            self.noise_ops += len(ops)
        for op in ops:
            self._apply(op)
        self.session.note_turn(" ".join(e.text for e in events))
        if self.session.should_jump():
            self.session.jump()

    def _apply(self, op: dict) -> None:
        kind, text = str(op["op"]).lower(), str(op["text"])
        if kind == "fact":
            self.session.record_event("open", text, priority=2)
        elif kind == "decision":
            self.session.record_event("decision", text,
                                      reason=str(op.get("reason", "")))
        elif kind == "goal":
            self.session.record_event("goal", text, status="pending")
        elif kind == "goal_done":
            target, best = None, 0
            words = set(text.lower().split())
            for g in self.session.rope.goals:
                overlap = len(words & set(str(g.text).lower().split()))
                if overlap > best:
                    best, target = overlap, g.num
            if target is not None and best >= 2:
                self.session.set_goal_status(target, "done")

    def context(self) -> str:
        return self.session.rope.render()

    def retriever(self):
        return lambda query: self.session.retrieve(query, k=3)

    def end_turn(self) -> None:
        self.turn_tokens.append(count_tokens(self.context()))

    def close(self) -> None:
        self.session.close()


# ------------------------------------------------------------- the sweep


def _hit(answer: str, probe: Probe) -> bool:
    lowered = answer.lower()
    return any(v.lower() in lowered for v in probe.expected_any)


def _captured(rig, probe: Probe) -> bool:
    """Is the ground truth present ANYWHERE in the rig's memory system —
    on the rope, or retrievable from the vault by value or by question?"""
    haystacks = [rig.context()]
    retrieve = rig.retriever()
    if retrieve is not None:
        for q in (*probe.expected_any, probe.question):
            haystacks.append(retrieve(q))
    joined = "\n".join(haystacks).lower()
    return any(v.lower() in joined for v in probe.expected_any)


@dataclass
class ConditionStats:
    name: str
    hits: int = 0
    total: int = 0
    captured: int = 0
    capture_losses: int = 0
    recall_losses: int = 0
    tokens: int = 0
    per_probe: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def capture_rate(self) -> float:
        return self.captured / self.total if self.total else 0.0


def run_seed(seed: int, n_turns: int, chatty: int, scribe) -> dict:
    scenario: Scenario = generate(seed, n_turns=n_turns, chatty=chatty)
    reader = ScriptedModel()

    rigs = {
        "scribe-rope": ScribeRope(scribe),
        "mech-rope": RopeRegime(rope_budget_tokens=600),
        "summary": SummaryRegime(budget_tokens=800),
    }
    stats = {name: ConditionStats(name) for name in rigs}

    for turn in range(1, n_turns + 1):
        events = scenario.turns[turn - 1]
        for rig in rigs.values():
            rig.observe(turn, events)
            rig.end_turn()
        for probe in scenario.probes_at(turn):
            for name, rig in rigs.items():
                st = stats[name]
                context = rig.context()
                retrieve = rig.retriever() if hasattr(rig, "retriever") else None
                ans = reader.answer(context, probe.question, retrieve)
                hit = _hit(ans.text, probe)
                st.total += 1
                st.hits += hit
                cap = _captured(rig, probe) if name != "summary" else (
                    any(v.lower() in context.lower() for v in probe.expected_any))
                st.captured += cap
                if not hit:
                    if cap:
                        st.recall_losses += 1
                    else:
                        st.capture_losses += 1
                st.per_probe.append({
                    "tag": probe.tag, "kind": probe.kind, "turn": probe.turn,
                    "bucket": probe.bucket, "hit": hit, "captured": cap,
                })

    for name, rig in rigs.items():
        stats[name].tokens = sum(rig.turn_tokens)
        if hasattr(rig, "close"):
            rig.close()

    out = {name: {
        "accuracy": round(st.accuracy, 4), "capture_rate": round(st.capture_rate, 4),
        "hits": st.hits, "total": st.total, "captured": st.captured,
        "capture_losses": st.capture_losses, "recall_losses": st.recall_losses,
        "context_tokens": st.tokens, "per_probe": st.per_probe,
    } for name, st in stats.items()}
    out["scribe_meta"] = {
        "ops_total": rigs["scribe-rope"].ops_total,
        "noise_ops": rigs["scribe-rope"].noise_ops,
        "parse_failures": getattr(scribe, "parse_failures", 0),
        "calls": getattr(scribe, "calls", 0),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scribe", choices=["perfect", "cmd"], default="perfect")
    ap.add_argument("--cmd", default="claude -p --model haiku")
    ap.add_argument("--seeds", type=int, nargs="+", default=[11, 12])
    ap.add_argument("--turns", type=int, default=40)
    ap.add_argument("--chatty", type=int, default=2)
    args = ap.parse_args()

    if args.scribe == "cmd":
        # Budget preflight: upper-bound each scribe call at rope budget (600)
        # + chatty turn (~250) + template (~350) tokens of input.
        calls = len(args.seeds) * args.turns
        est = estimate_cost(args.cmd, input_tokens=calls * 1200, calls=calls)
        enforce_budget(est)
        scribe_factory = lambda: CommandScribe(shlex.split(args.cmd))  # noqa: E731
    else:
        scribe_factory = PerfectScribe

    all_results = {}
    for seed in args.seeds:
        scribe = scribe_factory()
        print(f"— seed {seed} ({args.turns} turns, chatty={args.chatty}, "
              f"scribe={args.scribe}) …", flush=True)
        all_results[str(seed)] = run_seed(seed, args.turns, args.chatty, scribe)

    # ---- aggregate + report
    conditions = ["scribe-rope", "mech-rope", "summary"]
    agg = {c: {"hits": 0, "total": 0, "captured": 0,
               "capture_losses": 0, "recall_losses": 0} for c in conditions}
    for res in all_results.values():
        for c in conditions:
            for k in agg[c]:
                agg[c][k] += res[c][k]

    print(f"\nT10 — scribe fidelity ({len(args.seeds)} seeds × {args.turns} "
          f"turns, chatty={args.chatty}, n={agg['scribe-rope']['total']} probes/condition)")
    print(f"{'condition':<14}{'acc':>7}{'capture':>9}{'cap-loss':>10}{'rec-loss':>10}")
    for c in conditions:
        a = agg[c]
        acc = a["hits"] / a["total"]
        cap = a["captured"] / a["total"]
        print(f"{c:<14}{acc:>7.0%}{cap:>9.0%}{a['capture_losses']:>10}{a['recall_losses']:>10}")
    meta = [res["scribe_meta"] for res in all_results.values()]
    print(f"scribe ops: {sum(m['ops_total'] for m in meta)} total, "
          f"{sum(m['noise_ops'] for m in meta)} on filler-only turns, "
          f"{sum(m['parse_failures'] for m in meta)} unparseable lines, "
          f"{sum(m['calls'] for m in meta)} model calls")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"experiment": "t10-scribe-fidelity",
               "params": vars(args), "aggregate": agg, "seeds": all_results}
    (RESULTS_DIR / f"result-{args.scribe}.json").write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {RESULTS_DIR / f'result-{args.scribe}.json'}")


if __name__ == "__main__":
    main()
