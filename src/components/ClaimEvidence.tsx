import { cloneElement, type ReactElement, type ReactNode } from "react";
import { FileText, ExternalLink } from "lucide-react";
import { useDataset, type ScoreProvenance } from "../data/dataset";
import type { OfficialSourceManifestEntry } from "../types";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface ClaimEvidenceProps {
  /** Value-free entry returned by DatasetProvider; never pass a raw score. */
  entry: ScoreProvenance | null;
  modelName: string;
  benchmarkName: string;
  className?: string;
  /** Reuses an existing non-nested score button as the evidence trigger. */
  trigger?: ReactElement;
}

interface SourceManifestEvidenceProps {
  artifactId: string;
  policyVersion: string;
  sourceManifest: readonly OfficialSourceManifestEntry[];
  className?: string;
}

function safeHttpsHref(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

interface ExternalSourceLinkProps {
  href: string;
  className?: string;
  children: ReactNode;
}

/**
 * Render a source link only when it remains a credential-free HTTPS URL.
 * Dataset parsing enforces this for published artifacts; this component keeps
 * presentational call sites fail-closed for manually supplied test data too.
 */
export function ExternalSourceLink({
  href,
  className,
  children,
}: ExternalSourceLinkProps) {
  const safeHref = safeHttpsHref(href);
  if (!safeHref) return null;
  return (
    <a
      href={safeHref}
      target="_blank"
      rel="noreferrer"
      className={className}
    >
      {children}
    </a>
  );
}

function Definition({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px]">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 break-words text-foreground", mono && "font-mono")}>
        {children}
      </dd>
    </div>
  );
}

function SourceLink({ source }: { source: Readonly<OfficialSourceManifestEntry> }) {
  const href = safeHttpsHref(source.sourceUrl);
  if (!href) return <span>{source.sourceName}</span>;
  return (
    <ExternalSourceLink
      href={href}
      className="inline-flex items-center gap-1 text-primary hover:underline focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {source.sourceName} <ExternalLink className="h-3 w-3" aria-hidden="true" />
      <span className="sr-only"> (opens in a new tab)</span>
    </ExternalSourceLink>
  );
}

interface ResolvedClaimEvidence {
  entry: ScoreProvenance;
  official: NonNullable<ScoreProvenance["officialProvenance"]>;
  source: Readonly<OfficialSourceManifestEntry>;
  artifactId: string;
  policyVersion: string;
  releaseApprovalDecisionId: string;
}

const MANIFEST_PROVENANCE_FIELDS = [
  "sourceManifestKey",
  "officialSourceId",
  "sourceRevisionId",
  "sourceRevisionDecisionId",
  "sourceName",
  "sourceUrl",
  "sourceType",
  "sourceRevisionDefinitionSha256",
  "sourceSnapshotId",
  "snapshotContentSha256",
  "snapshotCapturedAt",
] as const;

function matchesManifestEntry(
  source: Readonly<OfficialSourceManifestEntry>,
  manifestEntry: Readonly<OfficialSourceManifestEntry>
): boolean {
  return MANIFEST_PROVENANCE_FIELDS.every((field) => source[field] === manifestEntry[field]);
}

function resolveClaimEvidence(
  entry: ScoreProvenance | null,
  officialRelease: ReturnType<typeof useDataset>["officialRelease"]
): ResolvedClaimEvidence | null {
  const official = entry?.officialProvenance;
  if (
    !entry ||
    !official ||
    !officialRelease ||
    !entry.claimId ||
    entry.captureStatus !== "published" ||
    entry.modelId !== official.displayIdentity.modelId ||
    entry.benchmarkId !== official.displayIdentity.benchmarkId
  ) {
    return null;
  }
  const source = officialRelease.sourceManifest.find(
    (candidate) =>
      candidate.sourceManifestKey === official.source.sourceManifestKey &&
      candidate.sourceSnapshotId === official.source.sourceSnapshotId &&
      matchesManifestEntry(official.source, candidate)
  );
  if (
    !source ||
    entry.officialSourceId !== source.officialSourceId ||
    entry.sourceSnapshotId !== source.sourceSnapshotId
  ) {
    return null;
  }
  return {
    entry,
    official,
    source,
    artifactId: officialRelease.artifactId,
    policyVersion: officialRelease.policyVersion,
    releaseApprovalDecisionId: officialRelease.releaseApprovalDecisionId,
  };
}

/**
 * The evidence content is exported for an existing parent popover to avoid
 * nesting interactive popovers around a score control.
 */
export function ClaimEvidenceDetails({
  entry,
  modelName,
  benchmarkName,
}: Omit<ClaimEvidenceProps, "className" | "trigger">) {
  const { officialRelease } = useDataset();
  const claim = resolveClaimEvidence(entry, officialRelease);
  if (!claim) return null;
  const { official, source } = claim;
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Claim evidence</h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {modelName} · {benchmarkName}
        </p>
      </div>

      <dl className="flex flex-col gap-1.5">
        <Definition label="Raw score" mono>
          {official.scoreRaw}
          {official.scoreUnit ? ` ${official.scoreUnit}` : ""}
        </Definition>
        <Definition label="Raw model" mono>{official.modelRaw}</Definition>
        <Definition label="Raw benchmark" mono>{official.benchmarkRaw}</Definition>
        <Definition label="Claim ID" mono>{claim.entry.claimId}</Definition>
        <Definition label="Snapshot ID" mono>{source.sourceSnapshotId}</Definition>
        <Definition label="Retrieved">
          <time dateTime={source.snapshotCapturedAt}>{source.snapshotCapturedAt}</time>
        </Definition>
        <Definition label="Reported">
          <time dateTime={claim.entry.date}>{claim.entry.date}</time>
        </Definition>
        <Definition label="Source URL"><SourceLink source={source} /></Definition>
        <Definition label="Source ID" mono>{source.officialSourceId}</Definition>
        <Definition label="Source type" mono>{source.sourceType}</Definition>
        <Definition label="Manifest key" mono>{source.sourceManifestKey}</Definition>
        <Definition label="Revision" mono>{source.sourceRevisionId}</Definition>
        <Definition label="Revision decision" mono>{source.sourceRevisionDecisionId}</Definition>
        <Definition label="Policy" mono>{claim.policyVersion}</Definition>
        <Definition label="Artifact" mono>{claim.artifactId}</Definition>
        <Definition label="Approval" mono>{claim.releaseApprovalDecisionId}</Definition>
        <Definition label="Claim review" mono>{official.claimReviewDecisionId}</Definition>
        <Definition label="Publication" mono>{official.claimPublicationDecisionId}</Definition>
        <Definition label="Capture" mono>{official.captureMethod}</Definition>
      </dl>

      <div className="border-t border-white/10 pt-3">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Display identity
        </h4>
        <dl className="mt-2 flex flex-col gap-1.5">
          <Definition label="Metric" mono>{official.displayIdentity.metric ?? "—"}</Definition>
          <Definition label="Split" mono>{official.displayIdentity.split ?? "—"}</Definition>
          <Definition label="Setting" mono>{official.displayIdentity.setting ?? "—"}</Definition>
          <Definition label="Evaluation" mono>
            {official.displayIdentity.evaluationVersion ?? "—"}
          </Definition>
        </dl>
      </div>

      <div className="border-t border-white/10 pt-3">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Evidence location
        </h4>
        <dl className="mt-2 flex flex-col gap-1.5">
          <Definition label="Kind" mono>{official.evidence.type}</Definition>
          <Definition label="Record" mono>{official.evidence.locator}</Definition>
          <Definition label="Model" mono>{official.evidence.modelLocator}</Definition>
          <Definition label="Benchmark" mono>{official.evidence.benchmarkLocator}</Definition>
          <Definition label="Score" mono>{official.evidence.scoreLocator}</Definition>
        </dl>
        {official.evidenceText ? (
          <p className="mt-2 rounded-md bg-white/5 px-2 py-1.5 text-xs text-muted-foreground">
            {official.evidenceText}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A compact control for one governed claim. It exposes provenance only; the
 * associated numeric value must still come from `getValue` at the caller.
 */
export function ClaimEvidence({
  entry,
  modelName,
  benchmarkName,
  className,
  trigger,
}: ClaimEvidenceProps) {
  const { officialRelease } = useDataset();

  // A score-like legacy/demo entry is never enough to claim governed evidence.
  // The manifest lookup also prevents a stale mixed snapshot from producing a
  // partial source link if a caller supplies inconsistent test data.
  if (!resolveClaimEvidence(entry, officialRelease)) return null;

  const label = `View claim evidence for ${modelName} on ${benchmarkName}`;
  const triggerProps = trigger?.props as Record<string, unknown> | undefined;
  const suppliedLabel =
    typeof triggerProps?.["aria-label"] === "string"
      ? triggerProps["aria-label"]
      : undefined;
  const evidenceTrigger = trigger
    ? cloneElement(
        trigger,
        {
          "aria-label":
            typeof suppliedLabel === "string" && suppliedLabel.trim().length > 0
              ? suppliedLabel
              : label,
        } as Record<string, unknown>
      )
    : (
      <button
        type="button"
        aria-label={label}
        className={cn(
          "data-claim-evidence rounded p-1 text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring",
          className
        )}
      >
        <FileText className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    );
  return (
    <Popover>
      <PopoverTrigger asChild>{evidenceTrigger}</PopoverTrigger>
      <PopoverContent align="end" className="max-h-[min(34rem,calc(100vh-2rem))] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto">
        <ClaimEvidenceDetails
          entry={entry}
          modelName={modelName}
          benchmarkName={benchmarkName}
        />
      </PopoverContent>
    </Popover>
  );
}

/** A release-level manifest surface used beside the future Official header. */
export function SourceManifestEvidence({
  artifactId,
  policyVersion,
  sourceManifest,
  className,
}: SourceManifestEvidenceProps) {
  if (sourceManifest.length === 0) return null;
  const sourceLabel = `${sourceManifest.length} source${sourceManifest.length === 1 ? "" : "s"}`;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring",
            className
          )}
          aria-label={`View release source manifest with ${sourceLabel}`}
        >
          Source manifest · {sourceLabel}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="max-h-[min(34rem,calc(100vh-2rem))] w-[min(30rem,calc(100vw-2rem))] overflow-y-auto">
        <div className="flex flex-col gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Release source manifest</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Artifact <span className="font-mono">{artifactId}</span> · policy{" "}
              <span className="font-mono">{policyVersion}</span>
            </p>
          </div>
          <ul className="flex flex-col gap-3">
            {sourceManifest.map((source) => (
              <li key={source.sourceManifestKey} className="rounded-md border border-white/10 bg-white/[0.03] p-2.5">
                <div className="text-xs font-medium text-foreground"><SourceLink source={source} /></div>
                <dl className="mt-2 flex flex-col gap-1.5">
                  <Definition label="Source ID" mono>{source.officialSourceId}</Definition>
                  <Definition label="Manifest key" mono>{source.sourceManifestKey}</Definition>
                  <Definition label="Revision" mono>{source.sourceRevisionId}</Definition>
                  <Definition label="Revision decision" mono>
                    {source.sourceRevisionDecisionId}
                  </Definition>
                  <Definition label="Snapshot ID" mono>{source.sourceSnapshotId}</Definition>
                  <Definition label="Retrieved">
                    <time dateTime={source.snapshotCapturedAt}>{source.snapshotCapturedAt}</time>
                  </Definition>
                  <Definition label="Source type" mono>{source.sourceType}</Definition>
                </dl>
              </li>
            ))}
          </ul>
        </div>
      </PopoverContent>
    </Popover>
  );
}
