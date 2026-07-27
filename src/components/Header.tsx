import { useEffect, useRef } from "react";
import { BookOpen, BarChart3, GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { DataMode } from "../data/dataMode";
import type { PublishedArtifactMetadata } from "../data/official";
import { SourceManifestEvidence } from "./ClaimEvidence";

interface HeaderProps {
  totalModels: number;
  totalBenchmarks: number;
  view: "table" | "compare";
  onViewChange: (v: "table" | "compare") => void;
  selectedCount: number;
  onOpenGlossary: () => void;
  dataModeLabel?: string;
  dataMode: DataMode;
  onDataModeChange: (m: DataMode) => void;
  officialUnavailableReason?: string;
  officialArtifact?: PublishedArtifactMetadata;
  officialUnavailableAnnouncement?: string | null;
  officialUnavailableAnnouncementId?: number;
}

export function Header({
  totalModels,
  totalBenchmarks,
  view,
  onViewChange,
  selectedCount,
  onOpenGlossary,
  dataModeLabel = "Awaiting data",
  dataMode,
  onDataModeChange,
  officialUnavailableReason,
  officialArtifact,
  officialUnavailableAnnouncement,
  officialUnavailableAnnouncementId,
}: HeaderProps) {
  const officialUnavailable = Boolean(officialUnavailableReason);
  const modeButtons = useRef<Record<DataMode, HTMLButtonElement | null>>({
    demo: null,
    official: null,
  });
  const previousMode = useRef<DataMode>(dataMode);

  // A mode switch clears data-dependent UI state in App. Return keyboard focus
  // to the newly active source control after that atomic commit so users do
  // not remain on a stale filter, comparison, or now-closed sheet trigger.
  useEffect(() => {
    if (previousMode.current !== dataMode) {
      modeButtons.current[dataMode]?.focus();
    }
    previousMode.current = dataMode;
  }, [dataMode]);

  return (
    <div className="flex flex-col gap-3 mb-4">
      <header className="glass flex flex-col gap-4 rounded-xl px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3.5">
          <div
            className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-500 font-extrabold text-white shadow-lg"
            role="img"
            aria-label="AI Benchmark Aggregator"
          >
            BA
          </div>
          <div>
            <h1 className="text-base font-semibold leading-tight tracking-tight sm:text-lg">
              AI Benchmark Aggregator
            </h1>
            <p className="font-mono text-[11px] text-muted-foreground">
              {totalModels} models · {totalBenchmarks} benchmarks · {dataModeLabel}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div
            className="flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/5 p-0.5"
            role="group"
            aria-label="Data source"
          >
            {(["demo", "official"] as const).map((m) => {
              const unavailable = m === "official" && officialUnavailable;
              return (
                <button
                  key={m}
                  type="button"
                  ref={(element) => {
                    modeButtons.current[m] = element;
                  }}
                  onClick={() => onDataModeChange(m)}
                  aria-pressed={dataMode === m}
                  aria-label={
                    unavailable
                      ? "Official claims unavailable; announce why"
                      : undefined
                  }
                  aria-describedby={m === "official" ? "official-data-status" : undefined}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring",
                    dataMode === m
                      ? "bg-primary text-primary-foreground shadow"
                      : unavailable
                        ? "cursor-help text-muted-foreground opacity-55"
                        : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {m === "demo" ? "Data" : unavailable ? "Official unavailable" : "Official"}
                </button>
              );
            })}
          </div>

          <Tabs value={view} onValueChange={(v) => onViewChange(v as "table" | "compare")}>
            <TabsList>
              <TabsTrigger value="table">
                <BarChart3 className="h-4 w-4" />
                Leaderboard
              </TabsTrigger>
              <TabsTrigger value="compare" disabled={selectedCount === 0}>
                <GitCompareArrows className="h-4 w-4" />
                Compare
                {selectedCount > 0 && (
                  <span className="ml-1 rounded-full bg-white/20 px-1.5 text-[11px] font-semibold">
                    {selectedCount}
                  </span>
                )}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <Button variant="glass" size="sm" onClick={onOpenGlossary} className="gap-1.5">
            <BookOpen className="h-4 w-4" />
            About benchmarks
          </Button>
        </div>
      </header>

      {officialUnavailableReason ? (
        <section
          id="official-data-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="glass rounded-xl px-5 py-3 text-xs text-muted-foreground"
        >
          <strong className="text-foreground">Official claims unavailable.</strong>{" "}
          {officialUnavailableReason} No benchmark data is currently published.
          {officialUnavailableAnnouncement ? (
            <span key={officialUnavailableAnnouncementId} className="sr-only">
              {officialUnavailableAnnouncement}
            </span>
          ) : null}
        </section>
      ) : dataMode === "official" && officialArtifact ? (
        <section
          id="official-data-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="glass flex flex-col gap-2 rounded-xl px-5 py-3 text-xs"
        >
          <p className="text-muted-foreground">
            <strong className="text-foreground">Official claims.</strong> Values are source-reported ledger claims; the UI presents them and does not recalculate benchmark scores.
          </p>
          <dl className="grid gap-x-5 gap-y-1 text-[11px] text-muted-foreground sm:grid-cols-3">
            <div>
              <dt className="inline font-medium text-foreground">Artifact: </dt>
              <dd className="inline font-mono">{officialArtifact.artifactId}</dd>
            </div>
            <div>
              <dt className="inline font-medium text-foreground">Approval: </dt>
              <dd className="inline font-mono">{officialArtifact.releaseApproval.decisionId}</dd>
            </div>
            <div>
              <dt className="inline font-medium text-foreground">Approved: </dt>
              <dd className="inline">
                <time dateTime={officialArtifact.releaseApproval.approvedAt}>
                  {officialArtifact.releaseApproval.approvedAt}
                </time>
              </dd>
            </div>
            <div className="sm:col-span-3">
              <dt className="inline font-medium text-foreground">Policy: </dt>
              <dd className="inline font-mono">{officialArtifact.policyVersion}</dd>
            </div>
          </dl>
          <div>
            <SourceManifestEvidence
              artifactId={officialArtifact.artifactId}
              policyVersion={officialArtifact.policyVersion}
              sourceManifest={officialArtifact.sourceManifest}
            />
          </div>
        </section>
      ) : dataMode === "official" ? (
        <section
          id="official-data-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="glass rounded-xl px-5 py-3 text-xs text-muted-foreground"
        >
          <strong className="text-foreground">Official claims selected.</strong>{" "}
          Release metadata is unavailable, so this state cannot make a stronger trust assertion.
        </section>
      ) : null}
      {!officialUnavailableReason && dataMode !== "official" ? (
        <span id="official-data-status" className="sr-only">
          Official claims are available. Select Official to view the governed release details.
        </span>
      ) : null}
    </div>
  );
}
