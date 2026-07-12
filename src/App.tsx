import { useMemo, useState, useEffect } from "react";
import type { BenchmarkCategory, Model } from "./types";
import { models as demoModels } from "./data/models";
import { benchmarks as demoBenchmarks } from "./data/benchmarks";
import { getScores } from "./data/scores";
function demoScores(): ReturnType<typeof getScores> { return getScores(); }
import { setActiveData } from "./data/registry";
import { loadOfficialData } from "./data/official";
import { computeRanking, sortModels } from "./lib/aggregate";
import { Header } from "./components/Header";
import { Filters } from "./components/Filters";
import { ScoreTable } from "./components/ScoreTable";
import { BenchmarkCard } from "./components/BenchmarkCard";
import { CategoryLeaders } from "./components/CategoryLeaders";
import { ModelDetail } from "./components/ModelDetail";
import { ModelComparison } from "./components/ModelComparison";
import { GlossaryDialog } from "./components/GlossaryDialog";
import { DATA_MODE_LABEL, type DataMode } from "./data/dataMode";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "./components/ui/sheet";
import { TooltipProvider } from "./components/ui/tooltip";
import {
  ToastProvider,
  ToastViewport,
  Toast,
  ToastDescription,
  ToastClose,
} from "./components/ui/toast";
import { useToast } from "./components/ui/use-toast";

const MAX_COMPARE = 6;

function Toaster() {
  const { toasts } = useToast();
  return (
    <ToastProvider swipeDirection="right">
      <ToastViewport>
        {toasts.map((t) => (
          <Toast key={t.id} {...t}>
            {t.description ? (
              <ToastDescription>{t.description}</ToastDescription>
            ) : null}
            <ToastClose />
          </Toast>
        ))}
      </ToastViewport>
    </ToastProvider>
  );
}

export default function App() {
  const [view, setView] = useState<"table" | "compare">("table");
  const [search, setSearch] = useState("");
  const [vendorFilter, setVendorFilter] = useState<Set<string>>(new Set());
  const [categoryFilter, setCategoryFilter] = useState<BenchmarkCategory | null>(null);
  const [openWeightsOnly, setOpenWeightsOnly] = useState(false);
  const [sort, setSort] = useState<{ benchmarkId: string | null; dir: "asc" | "desc" } | null>(null);
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [glossaryOpen, setGlossaryOpen] = useState(false);
  // Dual trust mode: demo synthetic data vs official ledger-backed claims
  // (ADR-003). The active dataset is published to the data registry below.
  const [dataMode, setDataMode] = useState<DataMode>("demo");

  const { toast } = useToast();

  // Select + publish the active dataset based on trust mode. Publish in an
  // effect (never during render) so React never sees a state update mid-render.
  useEffect(() => {
    if (dataMode === "official") {
      const off = loadOfficialData();
      setActiveData({ models: off.models, benchmarks: off.benchmarks, scores: off.scores });
      return;
    }
    setActiveData({ models: demoModels, benchmarks: demoBenchmarks, scores: demoScores() });
  }, [dataMode]);

  const { models: activeModels, benchmarks: activeBenchmarks } = useMemo(() => {
    if (dataMode === "official") {
      const off = loadOfficialData();
      return { models: off.models, benchmarks: off.benchmarks };
    }
    return { models: demoModels, benchmarks: demoBenchmarks };
  }, [dataMode]);

  const sourceUrls = useMemo(() => {
    if (dataMode !== "official") return [];
    const off = loadOfficialData();
    const sources = new Map<string, string>();

    const OFFICIAL_SOURCE_URLS: Record<string, string> = {
      fake_local_fixture: "https://huggingface.co/docs/hub/eval-results",
      hf_official_benchmark_discovery: "https://huggingface.co/api/datasets?filter=benchmark:official",
      swe_bench_verified_official_leaderboard: "https://www.swebench.com/",
      livecodebench_official_leaderboard: "https://livecodebench.github.io/leaderboard.html",
      mteb_leaderboard: "https://huggingface.co/spaces/mteb/leaderboard",
      bigcodebench_leaderboard: "https://bigcode-bench.github.io/",
    };

    off.scores.forEach((s) => {
      if (s.officialSourceId) {
        const url = OFFICIAL_SOURCE_URLS[s.officialSourceId];
        if (url) {
          sources.set(s.officialSourceId, url);
        }
      }
    });

    off.benchmarks.forEach((b) => {
      if (b.sourceUrl) {
        sources.set(b.name, b.sourceUrl);
      }
    });

    return Array.from(sources.entries()).map(([name, url]) => {
      const displayName = name.includes("http") ? "Source Link" : name
        .split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
      return { name: displayName, url };
    });
  }, [dataMode]);

  const vendors = useMemo(
    () => [...new Set(activeModels.map((m) => m.vendor))].sort(),
    [activeModels]
  );

  const visibleBenchmarks = useMemo(
    () =>
      categoryFilter
        ? activeBenchmarks.filter((b) => b.category === categoryFilter)
        : activeBenchmarks,
    [categoryFilter, activeBenchmarks]
  );

  const filteredModels = useMemo(() => {
    const q = search.trim().toLowerCase();
    return activeModels.filter((m) => {
      if (vendorFilter.size > 0 && !vendorFilter.has(m.vendor)) return false;
      if (openWeightsOnly && !m.openWeights) return false;
      if (q) {
        const hay = `${m.name} ${m.vendor} ${m.family}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [search, vendorFilter, openWeightsOnly, activeModels]);

  const sortedModels = useMemo(
    () => sortModels(filteredModels, sort, visibleBenchmarks),
    [filteredModels, sort, visibleBenchmarks]
  );

  const rankMap = useMemo(() => {
    const ranking = computeRanking(sortedModels, visibleBenchmarks);
    const map: Record<string, number> = {};
    ranking.forEach((r, i) => (map[r.model.id] = i + 1));
    return map;
  }, [sortedModels, visibleBenchmarks]);

  const selectedBenchmark = selectedBenchmarkId
    ? activeBenchmarks.find((b) => b.id === selectedBenchmarkId) ?? null
    : null;

  const selectedModel = selectedModelId
    ? activeModels.find((m) => m.id === selectedModelId) ?? null
    : null;

  const selectedModelObjects = useMemo(
    () =>
      selectedModels
        .map((id) => activeModels.find((m) => m.id === id))
        .filter((m): m is Model => m != null),
    [selectedModels, activeModels]
  );

  function handleSort(benchmarkId: string) {
    setSort((prev) => {
      if (prev?.benchmarkId === benchmarkId) {
        return { benchmarkId, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      return { benchmarkId, dir: "desc" };
    });
  }

  function toggleVendor(v: string) {
    setVendorFilter((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      return next;
    });
  }

  function toggleModelSelect(id: string) {
    if (selectedModels.includes(id)) {
      setSelectedModels(selectedModels.filter((x) => x !== id));
      toast({ description: "Removed from comparison" });
      return;
    }
    if (selectedModels.length >= MAX_COMPARE) {
      toast({ description: "Comparison is full (max 6)" });
      return;
    }
    setSelectedModels([...selectedModels, id]);
    toast({
      description: `Added to comparison (${selectedModels.length + 1}/${MAX_COMPARE})`,
    });
  }

  function clearFilters() {
    setSearch("");
    setVendorFilter(new Set());
    setCategoryFilter(null);
    setOpenWeightsOnly(false);
    setSort(null);
  }

  function handleDataModeChange(next: DataMode) {
    if (next === dataMode) return;
    setDataMode(next);
    // The active dataset changes: drop any selections/filters that reference
    // benchmark or model ids that may not exist in the other trust mode.
    setSearch("");
    setVendorFilter(new Set());
    setCategoryFilter(null);
    setOpenWeightsOnly(false);
    setSort(null);
    setSelectedBenchmarkId(null);
    setSelectedModelId(null);
    setSelectedModels([]);
  }

  function openModel(id: string) {
    setSelectedModelId(id);
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="mx-auto max-w-[1500px] px-4 py-4 sm:px-6 sm:py-5">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-white focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-black focus:shadow-lg"
        >
          Skip to content
        </a>
          <Header
            totalModels={activeModels.length}
            totalBenchmarks={activeBenchmarks.length}
            view={view}
            onViewChange={setView}
            selectedCount={selectedModels.length}
            onOpenGlossary={() => setGlossaryOpen(true)}
            dataModeLabel={DATA_MODE_LABEL[dataMode]}
            dataMode={dataMode}
            onDataModeChange={handleDataModeChange}
            sourceUrls={sourceUrls}
          />

          {view === "table" ? (
            <main id="main-content">
              <Filters
                search={search}
                onSearch={setSearch}
                vendors={vendors}
                vendorFilter={vendorFilter}
                onToggleVendor={toggleVendor}
                categoryFilter={categoryFilter}
                onCategory={setCategoryFilter}
                openWeightsOnly={openWeightsOnly}
                onToggleOpenWeights={setOpenWeightsOnly}
                onClear={clearFilters}
                resultCount={sortedModels.length}
              />
              <CategoryLeaders
                models={sortedModels}
                benchmarks={visibleBenchmarks}
                onOpenModel={openModel}
              />
              {sortedModels.length === 0 ? (
                <div className="glass-strong flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-16 text-center">
                  <p className="text-sm font-medium text-foreground">
                    No models match your filters
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Try clearing the vendor, category, or open-weights filters.
                  </p>
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="mt-1 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    Reset filters
                  </button>
                </div>
              ) : (
                <ScoreTable
                  models={sortedModels}
                  benchmarks={visibleBenchmarks}
                  sort={sort}
                  onSort={handleSort}
                  onBenchmarkClick={setSelectedBenchmarkId}
                  onOpenModel={openModel}
                  onClearSort={() => setSort(null)}
                  onToggleModelSelect={toggleModelSelect}
                  selectedModels={selectedModels}
                  rankMap={rankMap}
                />
              )}
            </main>
          ) : (
            <main id="main-content">
              <ModelComparison
                models={selectedModelObjects}
                benchmarks={activeBenchmarks}
                onOpenModel={openModel}
              />
            </main>
          )}

          <Sheet
            open={!!selectedBenchmark}
            onOpenChange={(o) => {
              if (!o) setSelectedBenchmarkId(null);
            }}
          >
            <SheetContent
              side="right"
              className="overflow-y-auto scroll-thin"
            >
              {selectedBenchmark && (
                <>
                  <SheetHeader className="sr-only">
                    <SheetTitle>{selectedBenchmark.fullName}</SheetTitle>
                  </SheetHeader>
                  <BenchmarkCard
                    benchmark={selectedBenchmark}
                    models={sortedModels}
                  />
                </>
              )}
            </SheetContent>
          </Sheet>

          <Sheet
            open={!!selectedModel}
            onOpenChange={(o) => {
              if (!o) setSelectedModelId(null);
            }}
          >
            <SheetContent
              side="right"
              className="overflow-y-auto scroll-thin"
            >
              {selectedModel && (
                <>
                  <SheetHeader className="sr-only">
                    <SheetTitle>{selectedModel.name}</SheetTitle>
                  </SheetHeader>
                  <ModelDetail
                    model={selectedModel}
                    models={sortedModels}
                    benchmarks={visibleBenchmarks}
                    selectedModels={selectedModels}
                    onToggleModelSelect={toggleModelSelect}
                  />
                </>
              )}
            </SheetContent>
          </Sheet>

          <GlossaryDialog
            open={glossaryOpen}
            onOpenChange={setGlossaryOpen}
            benchmarks={activeBenchmarks}
          />
        </div>
        <Toaster />
      </TooltipProvider>
  );
}
