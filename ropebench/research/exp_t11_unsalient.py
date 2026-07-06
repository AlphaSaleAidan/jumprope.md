"""T11 — unsalient capture: facts that only ever live inside tool output.

T10 proved a live scribe captures 100% of SALIENT facts — durable statements
made in prose ("the amber keel pipeline is pinned to build argon-1975").
Real sessions have a second fact class with no prose form at all: the port
in a stack trace, the digest in a diff hunk, the threshold in a config dump.
Nobody restates them; they scroll past inside machine blobs. If the scribe
does not dig them out at capture time, they die with the transcript.

PRE-REGISTERED PREDICTION (written before the live run): tool-fact capture
drops well below T10's 100% — the scribe prompt says "log durable facts"
but a value buried in a 20-line blob is exactly what a hurried scribe
skims past. If capture instead holds, the prompt generalizes and the
mechanical-capture-hooks tweak is optional rather than necessary.

Protocol: T10's harness (same scribe prompt — that is the point: no hint
that blobs matter), with 8 tool-output events injected per seed. Each tool
event's turn text is a short prose intro that does NOT contain the value,
followed by the raw blob. Four blob kinds: traceback (port), unified diff
(image digest), JSON config dump (max_retries), log tail (p99 ms).

Conditions:
  scribe-rope — live scribe sees prose+blob raw, must dig the value out
  mech-rope   — oracle logs the DISTILLED fact (upper bound; subclassed so
                the oracle never pastes a raw blob onto the rope)
  summary     — the blob enters the transcript and gets compressed away

Metrics reported OVERALL and TOOL-FACTS-ONLY — the headline is tool-fact
capture. Same deterministic reader everywhere.

Run (from ropebench/):
  python research/exp_t11_unsalient.py --scribe perfect          # harness check
  JROPE_BENCH_BUDGET_USD=1 python research/exp_t11_unsalient.py \
      --scribe cmd --cmd "claude -p --model haiku"               # live
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
from pathlib import Path

from research.exp_t10_scribe import (
    SCRIBE_PROMPT,
    CommandScribe,
    ConditionStats,
    PerfectScribe,
    ScribeRope,
    _captured,
    _hit,
)
from ropebench.models import ScriptedModel
from ropebench.pricing import enforce_budget, estimate_cost
from ropebench.regimes import RopeRegime, SummaryRegime
from ropebench.scenario import Event, Probe, Scenario, generate

# The candidate fix for the T11 capture gap: ONE added rule (--hint). If this
# recovers tool-fact capture, it ships in the skill prompt; if not, the fix
# is mechanical capture hooks, not prompting.
HINT_RULE = (
    "- Tool output (tracebacks, diffs, config dumps, log tails) often holds "
    "the ONLY copy of a critical value — a port, digest, threshold, "
    "latency. If a blob contains a specific measured value that could "
    "matter later, log it as a fact with the value verbatim, even when the "
    "surrounding output looks routine.\n"
)


HINTED_PROMPT = SCRIBE_PROMPT.replace(
    "- Output ONE JSON object per line",
    HINT_RULE + "- Output ONE JSON object per line",
)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "t11-unsalient"

SERVICES = ["gateway", "billing", "indexer", "notifier", "resolver", "archiver",
            "planner", "mailer"]


def _traceback_blob(rng: random.Random, service: str, port: int) -> str:
    return (
        f"$ pytest tests/integration/test_{service}.py -x\n"
        f"E       Traceback (most recent call last):\n"
        f'E         File "src/{service}/client.py", line {rng.randint(40, 220)}, in connect\n'
        f"E           sock.connect((host, self.port))\n"
        f'E         File "/usr/lib/python3.12/socket.py", line 836, in create_connection\n'
        f"E           raise err\n"
        f"E       ConnectionRefusedError: [Errno 111] Connection refused on port {port}\n"
        f"E       ----- {rng.randint(2, 9)} failed, {rng.randint(20, 80)} passed -----"
    )


def _diff_blob(rng: random.Random, service: str, digest: str) -> str:
    return (
        f"$ git diff deploy/{service}.yaml\n"
        f"@@ -{rng.randint(10, 60)},7 +{rng.randint(10, 60)},7 @@ spec:\n"
        f"       imagePullPolicy: IfNotPresent\n"
        f"-      image: registry.local/{service}:latest\n"
        f"+      image: registry.local/{service}@sha256:{digest}\n"
        f"       resources:\n"
        f"         limits:\n"
        f'           memory: "{rng.choice([256, 512, 1024])}Mi"'
    )


def _config_blob(rng: random.Random, service: str, retries: int) -> str:
    keys = {
        "timeout_s": rng.randint(5, 90), "pool_size": rng.randint(4, 64),
        "max_retries": retries, "backoff_ms": rng.choice([50, 100, 250]),
        "tls": True, "verify_hostname": True, "queue_depth": rng.randint(100, 900),
        "batch_size": rng.randint(10, 200),
    }
    body = ",\n".join(f'    "{k}": {json.dumps(v)}' for k, v in keys.items())
    return f"$ cat /etc/{service}/config.json\n{{\n{body}\n}}"


def _log_blob(rng: random.Random, service: str, p99: int) -> str:
    lines = [f"$ tail /var/log/{service}.log"]
    for _ in range(4):
        lines.append(f"INFO  worker-{rng.randint(1, 8)} handled batch "
                     f"({rng.randint(20, 400)} items, {rng.randint(3, 60)}ms)")
    lines.append(f"WARN  slow percentile check: p50={rng.randint(4, 30)}ms "
                 f"p95={rng.randint(40, 120)}ms p99={p99}ms")
    lines.append(f"INFO  heartbeat ok, uptime {rng.randint(2, 96)}h")
    return "\n".join(lines)


def inject_tool_events(scenario: Scenario, seed: int, n_tool: int = 8) -> None:
    """Append tool-output events + probes to an existing scenario in place.

    The prose intro NEVER contains the value; only the blob does. The
    'distilled' kwarg is the oracle's cheat-sheet (mech-rope upper bound)
    and doubles as the salience control: same value, prose form.
    """
    rng = random.Random(seed * 7919 + 13)
    kinds = ["port", "digest", "retries", "p99"]
    step = max(2, (scenario.n_turns - 8) // n_tool)
    for i in range(n_tool):
        service = SERVICES[i % len(SERVICES)]
        kind = kinds[i % len(kinds)]
        ref_turn = min(3 + i * step, scenario.n_turns - 3)
        if kind == "port":
            value = str(rng.randint(30000, 64999))
            blob = _traceback_blob(rng, service, int(value))
            intro = f"integration tests for the {service} are failing, output below:"
            distilled = f"{service} integration tests fail: connection refused on port {value}"
            question = f"What port was the {service} refusing connections on?"
        elif kind == "digest":
            value = "".join(rng.choice("0123456789abcdef") for _ in range(12))
            blob = _diff_blob(rng, service, value)
            intro = f"staged the {service} deploy pin, diff below:"
            distilled = f"{service} deploy pinned to image digest sha256:{value}"
            question = f"What image digest (sha256) was the {service} deploy pinned to?"
        elif kind == "retries":
            value = str(rng.randint(3, 19))
            blob = _config_blob(rng, service, int(value))
            intro = f"dumped the live {service} config for the audit:"
            distilled = f"live {service} config: max_retries={value}"
            question = f"What max_retries value was in the live {service} config?"
        else:
            value = str(rng.randint(180, 950))
            blob = _log_blob(rng, service, int(value))
            intro = f"checked the {service} latency logs:"
            distilled = f"{service} p99 latency measured at {value}ms"
            question = f"What was the {service} p99 latency in ms?"
        scenario.turns[ref_turn - 1].append(Event(
            kind="toolfact", text=f"{intro}\n{blob}", rope_section="open",
            rope_kwargs={"priority": 2, "distilled": distilled},
        ))
        probe_turn = min(ref_turn + rng.randint(8, 25), scenario.n_turns)
        scenario.probes.append(Probe(
            turn=probe_turn, kind="toolfact", tag=f"T{i + 1:02d}",
            question=question, expected_any=(value,), ref_turn=ref_turn,
        ))
    scenario.probes.sort(key=lambda p: p.turn)


class OracleToolRope(RopeRegime):
    """Mechanical upper bound that never pastes a raw blob onto the rope:
    tool events land as their distilled one-liner."""

    def _record(self, event: Event) -> None:
        distilled = event.rope_kwargs.get("distilled")
        if event.kind == "toolfact" and distilled:
            self.session.record_event("open", str(distilled), priority=2)
        else:
            super()._record(event)


class PerfectToolScribe(PerfectScribe):
    """Harness check: the oracle mapping incl. distilled tool facts."""

    def ops_for_turn(self, events: list[Event], rope_render: str) -> list[dict]:
        ops = super().ops_for_turn(events, rope_render)
        for e in events:
            if e.kind == "toolfact":
                ops.append({"op": "fact", "text": str(e.rope_kwargs["distilled"])})
        return ops


def run_seed(seed: int, n_turns: int, chatty: int, scribe) -> dict:
    scenario = generate(seed, n_turns=n_turns, chatty=chatty)
    inject_tool_events(scenario, seed)
    reader = ScriptedModel()
    rigs = {
        "scribe-rope": ScribeRope(scribe),
        "mech-rope": OracleToolRope(rope_budget_tokens=600),
        "summary": SummaryRegime(budget_tokens=800),
    }
    stats = {n: ConditionStats(n) for n in rigs}
    tool_stats = {n: ConditionStats(n + "/tool") for n in rigs}

    for turn in range(1, n_turns + 1):
        events = scenario.turns[turn - 1]
        for rig in rigs.values():
            rig.observe(turn, events)
            rig.end_turn()
        for probe in scenario.probes_at(turn):
            for name, rig in rigs.items():
                context = rig.context()
                retrieve = rig.retriever() if hasattr(rig, "retriever") else None
                ans = reader.answer(context, probe.question, retrieve)
                hit = _hit(ans.text, probe)
                cap = (_captured(rig, probe) if name != "summary" else
                       any(v.lower() in context.lower() for v in probe.expected_any))
                for st in ([stats[name]] +
                           ([tool_stats[name]] if probe.kind == "toolfact" else [])):
                    st.total += 1
                    st.hits += hit
                    st.captured += cap
                    if not hit:
                        if cap:
                            st.recall_losses += 1
                        else:
                            st.capture_losses += 1
                stats[name].per_probe.append({
                    "tag": probe.tag, "kind": probe.kind, "turn": probe.turn,
                    "hit": hit, "captured": cap,
                })

    for rig in rigs.values():
        if hasattr(rig, "close"):
            rig.close()
    return {
        "overall": {n: {"hits": s.hits, "total": s.total, "captured": s.captured,
                        "capture_losses": s.capture_losses,
                        "recall_losses": s.recall_losses,
                        "per_probe": s.per_probe}
                    for n, s in stats.items()},
        "tool_only": {n: {"hits": s.hits, "total": s.total, "captured": s.captured}
                      for n, s in tool_stats.items()},
        "scribe_meta": {"calls": getattr(scribe, "calls", 0),
                        "parse_failures": getattr(scribe, "parse_failures", 0),
                        "ops_total": rigs["scribe-rope"].ops_total,
                        "noise_ops": rigs["scribe-rope"].noise_ops},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scribe", choices=["perfect", "cmd"], default="perfect")
    ap.add_argument("--cmd", default="claude -p --model haiku")
    ap.add_argument("--hint", action="store_true",
                    help="add HINT_RULE to the scribe prompt (the T11b fix)")
    ap.add_argument("--seeds", type=int, nargs="+", default=[21, 22])
    ap.add_argument("--turns", type=int, default=40)
    ap.add_argument("--chatty", type=int, default=2)
    args = ap.parse_args()

    if args.scribe == "cmd":
        calls = len(args.seeds) * args.turns
        # blobs add ~300 tok on tool turns; bound each call at ~1500 tok input
        est = estimate_cost(args.cmd, input_tokens=calls * 1500, calls=calls)
        enforce_budget(est)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        raw_log = RESULTS_DIR / ("raw-hint.log" if args.hint else "raw.log")
        raw_log.write_text("")  # fresh audit trail per run
        kwargs = {"raw_log": raw_log}
        if args.hint:
            kwargs["prompt_template"] = HINTED_PROMPT
        make_scribe = lambda: CommandScribe(shlex.split(args.cmd), **kwargs)  # noqa: E731
    else:
        make_scribe = PerfectToolScribe

    results = {}
    for seed in args.seeds:
        print(f"— seed {seed} ({args.turns} turns, chatty={args.chatty}, "
              f"scribe={args.scribe}) …", flush=True)
        results[str(seed)] = run_seed(seed, args.turns, args.chatty, make_scribe())

    conditions = ["scribe-rope", "mech-rope", "summary"]
    for scope in ("overall", "tool_only"):
        agg = {c: {"hits": 0, "total": 0, "captured": 0} for c in conditions}
        for res in results.values():
            for c in conditions:
                for k in agg[c]:
                    agg[c][k] += res[scope][c][k]
        print(f"\nT11 {scope} (n={agg['scribe-rope']['total']}/condition)")
        print(f"{'condition':<14}{'acc':>7}{'capture':>9}")
        for c in conditions:
            a = agg[c]
            print(f"{c:<14}{a['hits'] / a['total']:>7.0%}"
                  f"{a['captured'] / a['total']:>9.0%}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"{args.scribe}-hint" if args.hint else args.scribe
    out = RESULTS_DIR / f"result-{suffix}.json"
    out.write_text(json.dumps({"experiment": "t11-unsalient-capture",
                               "params": vars(args), "seeds": results}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
