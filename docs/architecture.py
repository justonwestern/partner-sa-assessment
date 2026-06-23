"""
architecture.py
===============

Render the joint AWS + Arize reference architecture as docs/architecture.png.

The diagram is laid out as two ownership swimlanes so it answers the Partner-SA
"who owns what" question directly:

  * TOP  band  = AWS, the BUILD surface (Strands agent on Bedrock + Bedrock KB).
  * handoff    = the agent's own OpenTelemetry -> OpenInference spans, through a
                 production OTel Collector (tail-sampling + PII redaction).
  * BOTTOM band = Arize, the TRUST surface (Phoenix -> evals -> feedback loop),
                  with Arize AX + Alyx as the enterprise upgrade.

Uses matplotlib only (no graphviz dependency). Run:

    python docs/architecture.py            # writes docs/architecture.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless render
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle


OUT = Path(__file__).resolve().parent / "architecture.png"

# Palette (Arize-ish: dark ink, magenta accent, light blue; AWS orange).
INK = "#121221"
MAGENTA = "#D41C7A"
BLUE = "#A3DAF5"
AWS = "#FF9900"
GREY = "#6B7280"
PHX = "#5B3DF5"
AWS_TINT = "#FFF3E0"      # light orange band
ARIZE_TINT = "#FCE7F1"    # light magenta band


def _band(ax, x, y, w, h, label, edge, fill):
    ax.add_patch(Rectangle((x, y), w, h, linewidth=1.3, edgecolor=edge,
                           facecolor=fill, alpha=0.55, zorder=0,
                           linestyle=(0, (6, 4))))
    ax.text(x + 0.12, y + h - 0.22, label, ha="left", va="center",
            color=edge, fontsize=10, weight="bold", zorder=1)


def _box(ax, x, y, w, h, label, face, text_color="white", fontsize=9.5):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.2, edgecolor=INK, facecolor=face, zorder=2,
        )
    )
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            color=text_color, fontsize=fontsize, weight="bold", zorder=3, wrap=True)


def _arrow(ax, x1, y1, x2, y2, color=INK, style="-|>", ls="-", lw=1.7):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=14,
            linewidth=lw, color=color, linestyle=ls, zorder=1,
            connectionstyle="arc3,rad=0.0",
        )
    )


def build() -> Path:
    fig, ax = plt.subplots(figsize=(12.5, 7.6))
    ax.set_xlim(0, 12.5)
    ax.set_ylim(0, 7.6)
    ax.axis("off")

    ax.text(6.25, 7.25, "Better Together: AWS build surface + Arize trust surface",
            ha="center", fontsize=14, weight="bold", color=INK)
    ax.text(6.25, 6.85, "a Strands agent on Bedrock, observed and evaluated in Phoenix / Arize",
            ha="center", fontsize=10, color=GREY)

    # ---- TOP swimlane: AWS build surface ----
    _band(ax, 0.2, 5.0, 12.1, 1.55, "AWS  ·  the BUILD surface  (customer builds on AWS)",
          AWS, AWS_TINT)
    _box(ax, 0.45, 5.15, 1.6, 0.95, "User\nprompt", GREY)
    _box(ax, 2.35, 5.15, 2.5, 0.95, "Strands Agent\n(Claude Sonnet on Bedrock)", AWS, "black")
    _box(ax, 5.15, 5.15, 2.9, 0.95, "Bedrock KB tool · retrieve()\npartner-native primitive\n(Pydantic-validated out)", AWS, "black", 9.0)
    _arrow(ax, 2.05, 5.62, 2.35, 5.62)
    _arrow(ax, 4.85, 5.62, 5.15, 5.62)

    # ---- Handoff: telemetry through a production collector ----
    _box(ax, 4.55, 3.95, 3.1, 0.8, "Prod: OTel Collector\n(tail-sample + PII redact)", BLUE, "black", 9.0)
    _arrow(ax, 6.6, 5.15, 6.6, 4.75, color=INK)
    ax.text(6.78, 4.95, "agent telemetry:\nOpenTelemetry → OpenInference spans",
            color=INK, fontsize=8, va="center")
    ax.text(0.5, 4.62, "Laptop demo exports OTLP straight to local Phoenix; the collector is the "
                       "production hop (one place to sample + redact).",
            color=GREY, fontsize=8.0, va="center", style="italic")

    # ---- BOTTOM swimlane: Arize trust surface ----
    _band(ax, 0.2, 0.75, 12.1, 2.7, "Arize  ·  the TRUST surface  (is the agent right in prod?)",
          MAGENTA, ARIZE_TINT)
    # right-to-left flow so the prompt-patch can rise cleanly on the left
    _box(ax, 6.05, 2.25, 2.25, 0.95, "Local Phoenix\nlocalhost:6006", PHX)
    _box(ax, 3.15, 2.25, 2.7, 0.95, "Evals\nfrustration / tool-select /\nrubric judge (+ validation)", MAGENTA, "white", 8.7)
    _box(ax, 0.45, 2.25, 2.5, 0.95, "Feedback loop\nflag → human-gated\nprompt patch", MAGENTA, "white", 9.0)
    _box(ax, 9.05, 2.25, 3.15, 0.95, "Arize AX + Alyx\nretention · RBAC · online evals\n(enterprise upgrade)", INK, "white", 8.7)

    _arrow(ax, 6.1, 3.95, 7.1, 3.2)          # collector -> phoenix
    _arrow(ax, 6.05, 2.72, 5.85, 2.72)       # phoenix -> evals
    _arrow(ax, 3.15, 2.72, 2.95, 2.72)       # evals -> feedback
    # prompt patch rises on the left back to the agent
    _arrow(ax, 1.7, 3.2, 3.0, 5.15, color=MAGENTA, ls="--")
    ax.text(1.0, 4.25, "prompt\npatch", color=MAGENTA, fontsize=8.5, va="center", weight="bold")
    # enterprise upgrade: same spans to AX
    _arrow(ax, 8.3, 2.72, 9.05, 2.72, color=GREY, ls="--")
    ax.text(8.32, 3.05, "TRACE_BACKEND=ax\n(same OpenInference spans)",
            color=GREY, fontsize=7.6, va="center")

    # ---- Footnotes ----
    ax.text(0.3, 0.42, "MOCK_KB=true swaps the real Bedrock KB for canned docs/ so the full "
                       "trace → eval → feedback loop runs offline with no AWS account.",
            color=GREY, fontsize=8.5)

    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"Wrote {p}")
