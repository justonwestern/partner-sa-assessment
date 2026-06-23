"""
architecture.py
===============

Render the joint AWS + Arize reference architecture as docs/architecture.png.

Flow shown:
  user -> Strands/Bedrock agent -> Bedrock KB tool -> OpenInference spans
       -> local Phoenix -> evals -> feedback loop
  with Arize AX / Alyx drawn as the enterprise upgrade path.

Uses matplotlib only (no graphviz dependency) so it renders anywhere matplotlib
is installed. Run:

    python docs/architecture.py            # writes docs/architecture.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless render
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


OUT = Path(__file__).resolve().parent / "architecture.png"

# Arize-ish palette (dark ink, magenta accent, light blue) per brand notes.
INK = "#121221"
MAGENTA = "#D41C7A"
BLUE = "#A3DAF5"
AWS = "#FF9900"
GREY = "#6B7280"
PHX = "#5B3DF5"


def _box(ax, x, y, w, h, label, face, text_color="white", fontsize=10):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.2, edgecolor=INK, facecolor=face, zorder=2,
        )
    )
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            color=text_color, fontsize=fontsize, weight="bold", zorder=3, wrap=True)


def _arrow(ax, x1, y1, x2, y2, color=INK, style="-|>", ls="-"):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=14,
            linewidth=1.6, color=color, linestyle=ls, zorder=1,
        )
    )


def build() -> Path:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.5)
    ax.axis("off")

    ax.text(6, 6.2, "Better Together: AWS (Strands + Bedrock KB) observed in Phoenix / Arize",
            ha="center", fontsize=13, weight="bold", color=INK)

    # Row 1: the runtime path.
    _box(ax, 0.3, 4.6, 1.7, 1.0, "User\nprompt", GREY)
    _box(ax, 2.5, 4.6, 2.2, 1.0, "Strands Agent\n(Claude Sonnet\non Bedrock)", AWS, "black")
    _box(ax, 5.2, 4.6, 2.2, 1.0, "Bedrock KB tool\nretrieve()\n(Pydantic out)", AWS, "black")
    _box(ax, 7.9, 4.6, 2.0, 1.0, "OpenInference\nspans\n(manual + auto)", BLUE, "black")

    _arrow(ax, 2.0, 5.1, 2.5, 5.1)
    _arrow(ax, 4.7, 5.1, 5.2, 5.1)
    _arrow(ax, 7.4, 5.1, 7.9, 5.1)          # agent/tool -> spans
    _arrow(ax, 6.3, 4.6, 6.3, 4.6)          # (placeholder)

    # Row 2: observability + eval path (local default).
    _box(ax, 7.9, 2.9, 2.0, 1.0, "Local Phoenix\nlocalhost:6006", PHX)
    _box(ax, 5.2, 2.9, 2.2, 1.0, "Evals\nfrustration /\ntool-select / rubric", MAGENTA)
    _box(ax, 2.5, 2.9, 2.2, 1.0, "Feedback loop\ndetect + flag +\nprompt-patch stub", MAGENTA)

    _arrow(ax, 8.9, 4.6, 8.9, 3.9)          # spans -> phoenix
    _arrow(ax, 7.9, 3.4, 7.4, 3.4)          # phoenix -> evals
    _arrow(ax, 5.2, 3.4, 4.7, 3.4)          # evals -> feedback
    # Feedback loops back to the agent (prompt patch).
    _arrow(ax, 3.6, 3.9, 3.6, 4.6, color=MAGENTA, ls="--")
    ax.text(3.75, 4.25, "prompt\npatch", color=MAGENTA, fontsize=8, va="center")

    # Row 3: enterprise upgrade path.
    _box(ax, 7.9, 1.1, 2.0, 1.0, "Arize AX + Alyx\n(retention, RBAC,\nonline evals)", INK)
    _arrow(ax, 8.9, 2.9, 8.9, 2.1, color=GREY, ls="--")
    ax.text(10.1, 2.5, "enterprise\nupgrade\n(TRACE_BACKEND=ax)",
            color=GREY, fontsize=8, va="center")

    # Legend / notes.
    ax.text(0.3, 1.6, "Local default: traces -> Phoenix -> evals -> feedback loop.",
            color=INK, fontsize=9)
    ax.text(0.3, 1.2, "Same OpenInference spans upgrade to Arize AX by swapping the exporter.",
            color=GREY, fontsize=9)
    ax.text(0.3, 0.8, "MOCK_KB=true swaps the real Bedrock KB for canned docs/ for offline demos.",
            color=GREY, fontsize=9)

    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"Wrote {p}")
