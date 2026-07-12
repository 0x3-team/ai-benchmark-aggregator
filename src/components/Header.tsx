import { BookOpen, BarChart3, GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { DataMode } from "../data/dataMode";

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
  sourceUrls?: { name: string; url: string }[];
}

export function Header({
  totalModels,
  totalBenchmarks,
  view,
  onViewChange,
  selectedCount,
  onOpenGlossary,
  dataModeLabel = "Demo (synthetic)",
  dataMode,
  onDataModeChange,
  sourceUrls = [],
}: HeaderProps) {
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
            {(["demo", "official"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => onDataModeChange(m)}
                aria-pressed={dataMode === m}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring",
                  dataMode === m
                    ? "bg-primary text-primary-foreground shadow"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {m === "demo" ? "Demo" : "Official"}
              </button>
            ))}
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

      {dataMode === "official" && (
        <div className="glass flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-xl px-5 py-3 text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_#34d399]" />
            <span>
              <strong>Official Data Mode:</strong> Values are source-backed claims from the benchmark ledger, not independently recalculated scores.
            </span>
          </div>
          {sourceUrls.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-muted-foreground/30 hidden sm:inline">|</span>
              {sourceUrls.map((src) => (
                <a
                  key={src.url}
                  href={src.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:underline font-medium hover:text-primary/80 transition-colors"
                >
                  {src.name} ↗
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
