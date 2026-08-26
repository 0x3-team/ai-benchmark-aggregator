import { BookOpen, BarChart3, GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { PublishedArtifactMetadata } from "../data/official";
import { SourceManifestEvidence } from "./ClaimEvidence";

interface HeaderProps {
  totalModels: number;
  totalBenchmarks: number;
  view: "table" | "compare";
  onViewChange: (v: "table" | "compare") => void;
  selectedCount: number;
  onOpenGlossary: () => void;
  dataStatus: "awaiting-publication" | "official";
  officialUnavailableReason?: string;
  officialArtifact?: PublishedArtifactMetadata;
}

export function Header({
  totalModels,
  totalBenchmarks,
  view,
  onViewChange,
  selectedCount,
  onOpenGlossary,
  dataStatus,
  officialUnavailableReason,
  officialArtifact,
}: HeaderProps) {
  const visibleDataStatus =
    dataStatus === "official" ? "Official claims" : "Awaiting publication";

  return (
    <div className="flex flex-col gap-3 mb-4">
      <header className="glass flex min-w-0 flex-col gap-4 rounded-xl px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex min-w-0 items-center gap-3.5">
          <div
            className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-500 font-extrabold text-white shadow-lg"
            role="img"
            aria-label="AI Benchmark Aggregator"
          >
            BA
          </div>
          <div className="min-w-0">
            <h1 className="text-base font-semibold leading-tight tracking-tight sm:text-lg">
              AI Benchmark Aggregator
            </h1>
            <p className="font-mono text-[11px] text-slate-300">
              {totalModels} models · {totalBenchmarks} benchmarks · {visibleDataStatus}
            </p>
          </div>
        </div>

        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
          <Tabs value={view} onValueChange={(v) => onViewChange(v as "table" | "compare")}>
            <TabsList className="max-w-full">
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

          <Button variant="glass" size="sm" onClick={onOpenGlossary} className="w-full gap-1.5 sm:w-auto">
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
          className="glass rounded-xl px-5 py-3 text-xs text-slate-300"
        >
          <strong className="text-foreground">Awaiting Official publication.</strong>{" "}
          {officialUnavailableReason} No benchmark data is currently published in this build.
        </section>
      ) : dataStatus === "official" && officialArtifact ? (
        <section
          id="official-data-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="glass flex flex-col gap-2 rounded-xl px-5 py-3 text-xs"
        >
          <p className="text-slate-300">
            <strong className="text-foreground">Official claims.</strong> Values are source-reported ledger claims; the UI presents them and does not recalculate benchmark scores.
          </p>
          <dl className="grid gap-x-5 gap-y-1 text-[11px] text-slate-300 sm:grid-cols-3">
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
      ) : dataStatus === "official" ? (
        <section
          id="official-data-status"
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="glass rounded-xl px-5 py-3 text-xs text-slate-300"
        >
          <strong className="text-foreground">Official claims selected.</strong>{" "}
          Release metadata is unavailable, so this state cannot make a stronger trust assertion.
        </section>
      ) : null}
    </div>
  );
}
