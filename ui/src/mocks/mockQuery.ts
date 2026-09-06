/**
 * mocks/mockQuery.ts
 * ===================
 * Fabricates a plausible POST /api/query response for the mock backend.
 * This is deliberately simple pattern-matching on `contextSet.type` — it
 * exists only so the chat UI, grounding highlights, execution trace and
 * report button all have something real to render while the actual
 * orchestrator is being built. None of this logic should be mistaken for
 * "the orchestrator" — it's a stand-in, isolated entirely to mocks/.
 */
import { newLocalId } from "../lib/id";
import type {
  ContextSet,
  ExecutionTrace,
  GroundedSpan,
  GroundingEvidence,
  QueryResponse,
} from "../api/types";

/** Picks the first patchId referenced by a context set, for attaching
 *  evidence to a concrete patch in the mock response. */
function firstPatchId(contextSet: ContextSet): string {
  const item = contextSet.items[0];
  if (!item) return "unknown";
  if (item.kind === "patch") return item.patchId;
  if (item.kind === "area_selection") return item.resolvedPatchIds[0] ?? "unknown";
  return item.fileId; // uploaded_image — not a real patchId, but fine for a mock label
}

/** Finds `phrase` in `answer` and returns a GroundedSpan tied to
 *  `evidenceId`, or null if the phrase isn't present (defensive — every
 *  answer below is written to contain its own grounded phrase). */
function spanFor(answer: string, phrase: string, evidenceId: string): GroundedSpan | null {
  const start = answer.indexOf(phrase);
  if (start === -1) return null;
  return { start, end: start + phrase.length, evidenceId };
}

export function buildMockQueryResponse(_query: string, contextSet: ContextSet): QueryResponse {
  const patchId = firstPatchId(contextSet);
  const evidenceId = newLocalId("ev");

  let answer: string;
  let groundedPhrase: string;
  let evidence: GroundingEvidence;
  let executionTrace: ExecutionTrace;
  let confidence: number;

  switch (contextSet.type) {
    case "bitemporal_pair": {
      groundedPhrase = "built-up area";
      answer = `The ${groundedPhrase} has increased, concentrated along the river corridor, based on the two capture dates provided.`;
      evidence = {
        id: evidenceId,
        patchId,
        kind: "mask",
        geometry: "https://example.invalid/mock/change_mask.png",
        label: "increased built-up area",
      };
      executionTrace = {
        task: "change_vqa",
        modelsUsed: [{ name: "ChangeChat", role: "change_understanding" }],
        parameters: { threshold: 0.5 },
      };
      confidence = 0.74;
      break;
    }
    case "cross_modal_pair": {
      groundedPhrase = "water-covered regions";
      answer = `Combining the optical and SAR bands, the fused map highlights built-up and ${groundedPhrase} more reliably than either sensor alone.`;
      evidence = {
        id: evidenceId,
        patchId,
        kind: "mask",
        geometry: "https://example.invalid/mock/fusion_mask.png",
        label: "optical–SAR fused land cover",
      };
      executionTrace = {
        task: "cross_modal_fusion",
        modelsUsed: [{ name: "TerraFM", role: "optical_sar_fusion" }],
        parameters: { fusionMode: "gated_cross_attention" },
      };
      confidence = 0.68;
      break;
    }
    default: {
      // "single" — covers whole-patch, area-selection, and uploaded-image items alike.
      groundedPhrase = "agricultural field";
      answer = `The image mainly shows an ${groundedPhrase} bordered by a road to the north, with scattered tree cover.`;
      evidence = {
        id: evidenceId,
        patchId,
        kind: "bbox",
        geometry: [40, 30, 180, 150],
        label: groundedPhrase,
      };
      executionTrace = {
        task: "vqa",
        modelsUsed: [{ name: "TinyRS-R1", role: "vqa_captioning_grounding" }],
        parameters: {},
      };
      confidence = 0.81;
    }
  }

  const span = spanFor(answer, groundedPhrase, evidenceId);

  return {
    answer,
    groundedSpans: span ? [span] : [],
    evidence: [evidence],
    confidence,
    executionTrace,
    reportUrl: `/api/reports/${newLocalId("rep")}`,
  };
}

