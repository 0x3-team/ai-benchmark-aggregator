import { BookOpen, BarChart3, GitCompareArrows } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface HeaderProps {
  totalModels: number;
  totalBenchmarks: number;
  view: "table" | "compare";
  onViewChange: (v: "table" | "compare") => void;
  selectedCount: number;
  onOpenGlossary: () => void;
}

export function Header({
  totalModels,
  totalBenchmarks,
  view,
  onViewChange,
  selectedCount,
  onOpenGlossary,
}: HeaderProps) {
  return (
    <header className="glass mb-4 flex flex-col gap-4 rounded-xl px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3.5">
        <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-500 font-extrabold text-white shadow-lg">
          BA
        </div>
        <div>
          <h1 className="text-base font-semibold leading-tight tracking-tight sm:text-lg">
            AI Benchmark Aggregator
          </h1>
          <p className="font-mono text-[11px] text-muted-foreground">
            {totalModels} models · {totalBenchmarks} benchmarks · curated snapshot
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
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
  );
}
