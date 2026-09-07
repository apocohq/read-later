import type { Analysis, Content, CaptureEvent } from "../domain/index.js";

export const ANALYSIS_VERSION = "v1";

export interface EvaluationInput {
  content: Content;
  captures: CaptureEvent[];
  /** Assembled personal context (profile, active work, prior knowledge). */
  context: string;
}

/**
 * Turns content + context into a structured Analysis. Implementations call
 * the model with a schema; the article is passed as data, never as prompt.
 */
export interface Evaluator {
  evaluate(input: EvaluationInput): Promise<Analysis>;
}

/** Placeholder until the model-backed evaluator lands. Flags everything neutral. */
export class StubEvaluator implements Evaluator {
  async evaluate(input: EvaluationInput): Promise<Analysis> {
    const words = input.content.markdown.split(/\s+/).length;
    const neutral = 2.5;
    return {
      analysisVersion: ANALYSIS_VERSION,
      contentType: "opinion",
      topics: [],
      tldr: "Not yet evaluated.",
      mainClaims: [],
      newInsights: [],
      supportingEvidence: [],
      weaknesses: [],
      contextReasons: [],
      scores: {
        relevance: neutral,
        novelty: neutral,
        hardWon: neutral,
        evidence: neutral,
        actionability: neutral,
        sourceProximity: neutral,
        urgency: 0,
        redundancy: 0,
        hypeFomo: 0,
        promotionality: 0,
        readingCost: 0,
      },
      recommendation: "skim",
      confidence: 0,
      estimatedReadingMinutes: Math.max(1, Math.round(words / 230)),
      createdAt: new Date().toISOString(),
    };
  }
}

/** Model-backed evaluator. TODO: structured output call to the Anthropic API via the gateway. */
export class ModelEvaluator implements Evaluator {
  constructor(private readonly model: string) {}
  async evaluate(_input: EvaluationInput): Promise<Analysis> {
    throw new Error(`ModelEvaluator(${this.model}) not implemented`);
  }
}
