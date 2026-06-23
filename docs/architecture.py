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
AWS_TINT = "#FFF6EA"      # light orange band
ARIZE_TINT = "#FCE7F1"    # light magenta band

W, H = 16.0, 10.0         # canvas size in data units


def _band(ax, x, y, w, h, label, edge, fill):
    ax.add_patch(Rectangle((x, y), w, h, linewidth=1.4, edgecolor=edge,
                           facecolor=fill, alpha=0.6, zorder=0,
                           linestyle=(0, (7, 4))))
    ax.text(x + 0.18, y + h - 0.28, label, ha="left", va="center",
            color=edge, fontsize=11.5, weight="bold", zorder=1)


def _box(ax, x, y, w, h, label, face, text_color="white", fontsize=10.5):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.4, edgecolor=INK, facecolor=face, zorder=2,
        )
    )
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            color=text_color, fontsize=fontsize, weight="bold", zorder=3)


def _arrow(ax, x1, y1, x2, y2, color=INK, style="-|>", ls="-", lw=2.0,
           rad=0.0):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=18,
            linewidth=lw, color=color, linestyle=ls, zorder=4,
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def _note(ax, x, y, text, color=GREY, fontsize=9.0, style="italic",
          ha="left", weight="normal", boxed=False):
    bbox = None
    if boxed:
        bbox = dict(boxstyle="round,pad=0.3", facecolor="white",
                    edgecolor=color, linewidth=0.9, alpha=0.95)
    ax.text(x, y, text, color=color, fontsize=fontsize, va="center",
            ha=ha, style=style, weight=weight, zorder=5, bbox=bbox)


def build() -> Path:
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")

    # ---- Title block ----
    ax.text(W / 2, 9.55, "Better Together: AWS build surface + Arize trust surface",
            ha="center", fontsize=18, weight="bold", color=INK)
    ax.text(W / 2, 9.08, "a Strands agent on Bedrock, observed and evaluated in Phoenix / Arize",
            ha="center", fontsize=11.5, color=GREY)

    # =====================================================================
    # TOP swimlane: AWS build surface   (band y: 7.05 -> 8.75)
    # =====================================================================
    _band(ax, 0.3, 7.05, 15.4, 1.7,
          "AWS  ·  the BUILD surface  (customer builds on AWS)", AWS, AWS_TINT)

    top_y, top_h = 7.25, 1.05
    _box(ax, 0.7, top_y, 2.0, top_h, "User\nprompt", GREY)
    _box(ax, 3.4, top_y, 3.2, top_h,
         "Strands Agent\n(Claude Sonnet on Bedrock)", AWS, "black", 10.5)
    _box(ax, 7.3, top_y, 3.6, top_h,
         "Bedrock KB tool · retrieve()\npartner-native primitive\n(Pydantic-validated out)",
         AWS, "black", 9.8)

    _arrow(ax, 2.7, top_y + top_h / 2, 3.4, top_y + top_h / 2)
    _arrow(ax, 6.6, top_y + top_h / 2, 7.3, top_y + top_h / 2)

    # =====================================================================
    # HANDOFF: telemetry through a production collector   (mid band)
    # =====================================================================
    coll_x, coll_y, coll_w, coll_h = 6.0, 5.15, 3.9, 0.95
    _box(ax, coll_x, coll_y, coll_w, coll_h,
         "Prod: OTel Collector\n(tail-sample + PII redact)", BLUE, "black", 10.0)

    # vertical hop from agent/KB down into the collector
    hop_x = coll_x + coll_w / 2
    _arrow(ax, hop_x, top_y, hop_x, coll_y + coll_h, color=INK)
    _note(ax, hop_x + 0.35, (top_y + coll_y + coll_h) / 2 + 0.05,
          "agent telemetry:\nOpenTelemetry → OpenInference spans",
          color=INK, fontsize=9.0, style="normal", ha="left")

    # laptop-vs-prod aside, parked in clear space on the right
    _note(ax, 11.05, 5.55,
          "Laptop demo exports OTLP straight\n"
          "to local Phoenix; the collector is the\n"
          "production hop (one place to\nsample + redact).",
          color=GREY, fontsize=8.8, ha="left", boxed=True)

    # =====================================================================
    # BOTTOM swimlane: Arize trust surface   (band y: 0.9 -> 4.55)
    # =====================================================================
    _band(ax, 0.3, 0.9, 15.4, 3.65,
          "Arize  ·  the TRUST surface  (is the agent right in prod?)",
          MAGENTA, ARIZE_TINT)

    bot_y, bot_h = 2.45, 1.05
    _box(ax, 8.0, bot_y, 3.0, bot_h, "Local Phoenix\nlocalhost:6006", PHX)
    _box(ax, 4.25, bot_y, 3.2, bot_h,
         "Evals\nfrustration · tool-select ·\nrubric judge (+ validation)",
         MAGENTA, "white", 9.5)
    _box(ax, 0.7, bot_y, 3.0, bot_h,
         "Feedback loop\nflag → human-gated\nprompt patch", MAGENTA, "white", 9.8)
    _box(ax, 11.9, bot_y, 3.6, bot_h,
         "Arize AX + Alyx\nretention · RBAC · online evals\n(enterprise upgrade)",
         INK, "white", 9.5)

    bot_mid = bot_y + bot_h / 2

    # collector -> local phoenix
    _arrow(ax, hop_x, coll_y, 9.5, bot_y + bot_h, color=INK, rad=-0.12)
    # phoenix -> evals -> feedback (right to left)
    _arrow(ax, 8.0, bot_mid, 7.45, bot_mid)
    _arrow(ax, 4.25, bot_mid, 3.7, bot_mid)

    # feedback loop -> prompt patch back up to the agent (clean left riser)
    _arrow(ax, 2.2, bot_y + bot_h, 2.2, top_y, color=MAGENTA, ls="--", rad=0.0)
    _note(ax, 2.45, (bot_y + bot_h + top_y) / 2, "prompt\npatch",
          color=MAGENTA, fontsize=9.5, style="normal", weight="bold", ha="left")

    # enterprise upgrade: same spans flow to Arize AX
    _arrow(ax, 11.0, bot_mid, 11.9, bot_mid, color=GREY, ls="--")
    _note(ax, 11.45, bot_mid + 0.78,
          "TRACE_BACKEND=ax\n(same OpenInference spans)",
          color=GREY, fontsize=8.6, style="normal", ha="center")

    # =====================================================================
    # Footnote
    # =====================================================================
    _note(ax, 0.4, 0.45,
          "MOCK_KB=true swaps the real Bedrock KB for canned docs/ so the full "
          "trace → eval → feedback loop runs offline with no AWS account.",
          color=GREY, fontsize=9.2, style="italic", ha="left")

    fig.savefig(OUT, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"Wrote {p}")
