"""Codex agent with the built-in image-generation tool disabled, for $0 subscription auth.

WHY THIS EXISTS
---------------
codex-cli 0.135.0 ships an ``image_generation`` feature (``stable``, default ON) whose
built-in ``image_gen`` tool targets the model ``gpt-image-2`` — which does not exist on
the ChatGPT-subscription backend. On BiomniBench data-analysis tasks the agent is prone to
*spuriously* reaching for image generation (e.g. when it decides to "produce a figure"),
the turn 400s ("InvalidImageRequest"), and codex exits WITHOUT writing ``/app/answer.txt``.
Harbor still reports the trial as completed, so this surfaces as a silent non-delivery — it
corrupted a meaningful fraction of the first variant run (we recovered answers from the
reasoning trace, but that is lossy and unnecessary).

THE FIX
-------
Disable the feature at the source. ``codex`` documents ``--disable <name>`` /
``-c features.<name>=false`` as the toggle for any feature, and ``codex features list``
confirms the effective state of ``image_generation`` flips ``true -> false`` with the flag.
With the feature off the ``image_gen`` tool is never offered to the model, so the 400 can
no longer happen. (The bundled ``skills/.system/imagegen`` SKILL.md may still materialise
on disk — codex re-creates it each run — but it is inert text once the tool is gone.)

We inject the flag through ``build_cli_flags()`` — the same override seam the antigravity
agent uses for ``--print-timeout`` — so it lands in the ``codex exec`` command alongside the
stock ``-c model_reasoning_effort=...`` flags. Everything else (ChatGPT OAuth via
``CODEX_FORCE_AUTH_JSON``, model selection, trajectory capture) is inherited unchanged.

USAGE
-----
  env -u OPENAI_API_KEY CODEX_FORCE_AUTH_JSON=1 \
  harbor run --path <task> \
    --agent-import-path benchmarks.harbor_agents.codex_no_imagegen:CodexNoImagegen \
    --model gpt-5.5 --disable-verification -n 1 -o <out>

Override the flag (e.g. to A/B test) via env CODEX_DISABLE_IMAGEGEN=0 to fall back to stock.
"""

from __future__ import annotations

from harbor.agents.installed.codex import Codex
from harbor.utils.env import parse_bool_env_value

# The codex feature that gates the built-in image_gen tool. `codex features list` reports
# this as a `stable` feature defaulting to true; `-c features.image_generation=false`
# (validated against `--strict-config`) turns it off.
_DISABLE_FLAG = "-c features.image_generation=false"


class CodexNoImagegen(Codex):
    """Stock Codex with ``features.image_generation`` forced off (kills the gpt-image-2 400)."""

    def build_cli_flags(self) -> str:
        base = super().build_cli_flags()
        # Opt back into stock behavior with CODEX_DISABLE_IMAGEGEN=0/false (default: disable).
        if not parse_bool_env_value(
            self._get_env("CODEX_DISABLE_IMAGEGEN"),
            name="CODEX_DISABLE_IMAGEGEN",
            default=True,
        ):
            return base
        return f"{base} {_DISABLE_FLAG}".strip()
