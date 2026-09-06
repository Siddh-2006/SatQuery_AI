# Change detection / change-VQA — PLACEHOLDER (model under development)

**Status: not ready.** This file is a placeholder so the folder shape
matches every other specialist tool (see [`../README.md`](../README.md)).
There is no working backend for this model yet, so
`orchestrator/tools/registry.py` does not register a tool for it, and the
orchestrator never tells the LLM this capability exists. A `bitemporal_pair`
query today returns a plain `unsupported_task` error instead
(`orchestrator/DESIGN.md` §4/§13).

## What this will eventually be

Per the SIH idea doc, this slot is planned as a **ChangeChat / DeltaVLM**
-style model: encode `image_t1` and `image_t2` separately with TerraFM,
compute an explicit difference embedding between them (not just
concatenation), then feed `[emb_t1, emb_t2, delta]` through a projector
into an LLM fine-tuned on CDVQA (change-based visual question answering).
Candidate architecture references the idea doc calls out: DeltaVLM (2025)
and TCSSM (arXiv:2508.08974, 2025) for domain-generalized change-VQA.

## When this is ready, fill in below (mirror `eocaptioner_s1_s2/SYSTEM_PROMPT.md`'s shape)

- The exact query template shape(s) this model needs (does it take one
  combined prompt referencing both images, or two separate calls?).
- Hard constraints / things that silently fail if mis-templated.
- The tool's JSON parameter schema (goes in `capabilities.json` here).
- A few worked examples: user question -> tool call -> how to phrase the
  final answer.

Ask to have this wired into `orchestrator/tools/` once it's ready.
