import type { DatasetInput } from "./dataset";
import type { DataMode } from "./dataMode";
import type { OfficialLoadResult, OfficialPublishedResult } from "./official";

/**
 * The only state that may cross the application data boundary.  `mode` and
 * `data` are one discriminated value so a render cannot label Demo values as
 * Official (or the reverse) while a switch is in progress.
 */
export type DatasetSelection =
  | {
      readonly mode: "demo";
      readonly data: DatasetInput;
      readonly official: OfficialLoadResult;
    }
  | {
      readonly mode: "official";
      readonly data: DatasetInput;
      readonly official: OfficialPublishedResult;
    };

/**
 * Select the provider snapshot synchronously from an already validated
 * Official-load result.  Parsing and integrity checks happen before this
 * function is called; an unavailable result always retains the Demo snapshot.
 */
export function selectDataset(
  requestedMode: DataMode,
  demo: DatasetInput,
  official: OfficialLoadResult
): DatasetSelection {
  if (requestedMode === "official" && official.availability === "published") {
    return Object.freeze({
      mode: "official" as const,
      data: official.data,
      official,
    });
  }

  return Object.freeze({
    mode: "demo" as const,
    data: demo,
    official,
  });
}
