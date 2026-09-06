# Optical-SAR cross-modal fusion — PLACEHOLDER (model under development)

**Status: not ready.** Placeholder file, matching the shape of every
other specialist tool folder (see [`../README.md`](../README.md)). No
working backend exists yet, so this tool is not registered
(`orchestrator/tools/registry.py`) and a `cross_modal_pair` query today
returns `unsupported_task` (`orchestrator/DESIGN.md` §4/§13).

## What this will eventually be

Per the SIH idea doc: fusion-at-encoder-level using TerraFM's dual-branch
backbone (a SAR branch + an optical branch) with gated cross-attention
fusion before the LLM, inspired by "Gated-Guided Fusion for Optical-SAR
Object Detection" (2026). Goal: extract complementary information from a
co-registered optical + SAR pair of the same area (e.g. "use the optical
and SAR images together to identify built-up and water-covered
regions").

## When this is ready, fill in below

- Exact query template shape(s).
- Hard constraints.
- JSON parameter schema (goes in `capabilities.json` here).
- Worked examples.

Ask to have this wired into `orchestrator/tools/` once it's ready.
