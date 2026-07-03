"""§8.3 — Density benchmark: symbolic-en must cut ≥40% of prose tokens.

The fixture pair states identical facts; the dense form is produced by the
profile itself (no hand-tuned parallel text), so the measured reduction is
what real rope writes get.
"""

from __future__ import annotations

from jumping_rope.notation import get_profile
from jumping_rope.tokens import count_tokens

PROSE_FIXTURE = (
    "The authentication module is now completed and the database migration was "
    "finished successfully, which leads to the deployment being unblocked. "
    "We are currently working on the configuration of the environment as well as "
    "the documentation of the repository. "
    "It should be noted that the integration test suite is currently failing "
    "because of the fact that a dependency of the application was upgraded. "
    "The performance of the implementation is really very acceptable, and the "
    "requirements of the function are basically satisfied. "
    "We decided to use the sqlite database in order to avoid running a server, "
    "and this decision leads to a simpler deployment of the application. "
    "The review of the repository is still pending, and we are waiting for the "
    "maintainer of the project to respond to the request."
)


def test_symbolic_en_reduction_at_least_40_percent() -> None:
    profile = get_profile("symbolic-en")
    dense = profile.densify(PROSE_FIXTURE)
    prose_tokens = count_tokens(PROSE_FIXTURE)
    dense_tokens = count_tokens(dense)
    reduction = 1 - dense_tokens / prose_tokens
    print(
        f"\n[density] prose={prose_tokens} tokens, symbolic-en={dense_tokens} tokens, "
        f"reduction={reduction:.1%}"
    )
    assert reduction >= 0.40, f"only {reduction:.1%} reduction"
    # Information must survive: key facts still present.
    for fact in ("auth", "db", "migr", "sqlite", "deploy"):
        assert fact in dense.lower()


def test_cjk_dense_measured_and_reported() -> None:
    """cjk-dense is measured honestly — asserted only to not exceed prose."""
    profile = get_profile("cjk-dense")
    dense = profile.densify(PROSE_FIXTURE)
    prose_tokens = count_tokens(PROSE_FIXTURE)
    dense_tokens = count_tokens(dense)
    print(
        f"\n[density] prose={prose_tokens} tokens, cjk-dense={dense_tokens} tokens, "
        f"reduction={1 - dense_tokens / prose_tokens:.1%}"
    )
    assert dense_tokens < prose_tokens


def test_densify_is_deterministic() -> None:
    profile = get_profile("symbolic-en")
    assert profile.densify(PROSE_FIXTURE) == profile.densify(PROSE_FIXTURE)


def test_legend_within_120_tokens() -> None:
    for name in ("symbolic-en", "cjk-dense"):
        legend = get_profile(name).legend()
        tokens = count_tokens(legend)
        print(f"\n[legend] {name}: {tokens} tokens")
        assert tokens <= 120, f"{name} legend is {tokens} tokens"
