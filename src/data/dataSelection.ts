import type { DatasetInput } from "./dataset";
import type {
  OfficialLoadResult,
  OfficialPublishedResult,
  OfficialUnavailableResult,
} from "./official";

/**
 * The tracked unavailable artifact resolves to this immutable empty snapshot.
 * It is deliberately not a fallback catalog: only a governed published result
 * can supply models, benchmarks, and scores to the production provider.
 */
export const AWAITING_PUBLICATION_DATASET: DatasetInput = Object.freeze({
  models: Object.freeze([]),
  benchmarks: Object.freeze([]),
  scores: Object.freeze([]),
});

export type OfficialDatasetSelection =
  | {
      readonly status: "awaiting-publication";
      readonly data: DatasetInput;
      readonly official: OfficialUnavailableResult;
      readonly key: string;
    }
  | {
      readonly status: "official";
      readonly data: DatasetInput;
      readonly official: OfficialPublishedResult;
      readonly key: string;
    };

/**
 * Select the production provider snapshot from an already validated Official
 * load result. Unavailable never falls back to sample, local, or synthetic
 * data; it returns the honest awaiting-publication snapshot.
 */
export function selectOfficialDataset(
  official: OfficialLoadResult
): OfficialDatasetSelection {
  if (official.availability === "published") {
    return Object.freeze({
      status: "official" as const,
      data: official.data,
      official,
      key: `official:${official.artifact.artifactId}:${official.artifact.manifest.contentSha256}`,
    });
  }

  return Object.freeze({
    status: "awaiting-publication" as const,
    data: AWAITING_PUBLICATION_DATASET,
    official,
    key: `awaiting-publication:${official.artifactId ?? "unidentified"}`,
  });
}
