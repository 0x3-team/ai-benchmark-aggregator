import { lazy, Suspense, useMemo, useState } from "react";
import type { BenchmarkCategory } from "./types";
import {
  DatasetProvider,
  useDataset,
  type DatasetModel,
} from "./data/dataset";
import { loadOfficialData, type OfficialLoadResult } from "./data/official";
import { selectOfficialDataset } from "./data/dataSelection";
import {
  computeRanking,
  sortModels,
  type RankRow,
} from "./lib/aggregate";
import { Header } from "./components/Header";
import { Filters } from "./components/Filters";
import { ScoreTable } from "./components/ScoreTable";
import { CategoryLeaders } from "./components/CategoryLeaders";
import { GlossaryDialog } from "./components/GlossaryDialog";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
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

/**
 * Chart-heavy secondary surfaces are code-split with React.lazy so the
 * deferred chunk (recharts/motion/evilcharts chart layer) is not part of the
 * primary table workflow's eager load, and so the loading/error/trust UI —
 * Header, Filters, ScoreTable, ClaimEvidence — stays in the eager entry. Each
 * is only ever *rendered* while its owning Sheet/dialog is open (conditional),
 * so the fallback briefly appears only on cold open, never on the primary
 * path. The primary workflow and accessibility are untouched: the Suspense
 * boundary drops the loading state into the already-conditional Sheet content.
 */
const ModelComparison = lazy(() =>
  import("./components/ModelComparison").then((m) => ({ default: m.ModelComparison }))
);
const ModelDetail = lazy(() =>
  import("./components/ModelDetail").then((m) => ({ default: m.ModelDetail }))
);
const BenchmarkCard = lazy(() =>
  import("./components/BenchmarkCard").then((m) => ({ default: m.BenchmarkCard }))
);
// The "Benchmark catalog" share-of-categories pie is a chart-heavy secondary
// surface inside the primary table view. Splitting it moves the recharts Pie
// core to a deferred chunk so the primary table workflow's eager load stays
// under the approved 1,100,000-byte budget. It keeps its Card chrome eager,
// so layout stays stable; only the pie body suspends on cold render with an
// accessible `role="status"` fallback.
const CatalogSharePie = lazy(() =>
  import("./components/charts/CatalogSharePie").then((m) => ({
    default: m.CatalogSharePie,
  }))
);

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
  const officialLoadResult = useMemo(() => loadOfficialData(), []);
  return <AppWithDataSources officialLoadResult={officialLoadResult} />;
}

/**
 * The production App supplies only the fixed Official loader above. This seam
 * lets UI tests exercise a previously verified published result without giving
 * the runtime a second artifact import, sample path, or fallback dataset.
 */
export function AppWithDataSources({
  officialLoadResult,
}: {
  officialLoadResult: OfficialLoadResult;
}) {
  const selection = useMemo(
    () => selectOfficialDataset(officialLoadResult),
    [officialLoadResult]
  );

  return (
    <AppErrorBoundary
      resetKey={selection.data}
      sourceLabel="Official"
    >
      <DatasetProvider key={selection.key} data={selection.data}>
        <AppContent
          dataStatus={selection.status}
          officialLoadResult={selection.official}
        />
      </DatasetProvider>
    </AppErrorBoundary>
  );
}

interface AppContentProps {
  dataStatus: "awaiting-publication" | "official";
  officialLoadResult: OfficialLoadResult;
}

function AppContent({
  dataStatus,
  officialLoadResult,
}: AppContentProps) {
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
  const [showAllBenchmarks, setShowAllBenchmarks] = useState(false);
  const [showModelsWithNoPublishedScores, setShowModelsWithNoPublishedScores] = useState(false);
  const { toast } = useToast();

  const officialUnavailableReason =
    officialLoadResult.availability === "unavailable"
      ? officialLoadResult.reason
      : undefined;
  const officialArtifact =
    officialLoadResult.availability === "published"
      ? officialLoadResult.artifact
      : undefined;

  // Every data-dependent render reads the atomic Official provider snapshot
  // selected above this component.
  const {
    models: activeModels,
    benchmarks: activeBenchmarks,
    getValue,
  } = useDataset();

  const vendors = useMemo(
    () => [...new Set(activeModels.map((m) => m.vendor))].sort(),
    [activeModels]
  );

  const categoryBenchmarks = useMemo(
    () =>
      categoryFilter
        ? activeBenchmarks.filter((b) => b.category === categoryFilter)
        : activeBenchmarks,
    [categoryFilter, activeBenchmarks]
  );

  // Limit benchmark columns to avoid rendering too many DOM nodes at once.
  // When "All" is selected and showAllBenchmarks is false, show the first 12.
  const visibleBenchmarks = useMemo(
    () =>
      !categoryFilter && !showAllBenchmarks && categoryBenchmarks.length > 12
        ? categoryBenchmarks.slice(0, 12)
        : categoryBenchmarks,
    [categoryBenchmarks, categoryFilter, showAllBenchmarks]
  );

  const hiddenBenchmarkCount = categoryBenchmarks.length - visibleBenchmarks.length;

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

  // The presentation cohort is the entire immutable dataset snapshot. Search,
  // vendor, category, and open-weights filters only control visible rows; they
  // cannot promote a partial or filtered model into an overall leader.
  const presentationRanking = useMemo(
    () => computeRanking(activeModels, activeBenchmarks, getValue),
    [activeModels, activeBenchmarks, getValue]
  );

  const rankMap = useMemo(() => {
    const map: Record<string, RankRow> = {};
    presentationRanking.forEach((row) => (map[row.model.id] = row));
    return map;
  }, [presentationRanking]);

  const modelsWithPublishedScores = useMemo(
    () =>
      showModelsWithNoPublishedScores
        ? filteredModels
        : filteredModels.filter((model) => (rankMap[model.id]?.covered ?? 0) > 0),
    [filteredModels, rankMap, showModelsWithNoPublishedScores]
  );

  const hasModelsWithNoPublishedScores = useMemo(
    () => presentationRanking.some((row) => row.covered === 0),
    [presentationRanking]
  );

  const sortedModels = useMemo(
    () =>
      sortModels(
        modelsWithPublishedScores,
        sort,
        visibleBenchmarks,
        activeBenchmarks,
        getValue,
        presentationRanking
      ),
    [
      modelsWithPublishedScores,
      sort,
      visibleBenchmarks,
      activeBenchmarks,
      getValue,
      presentationRanking,
    ]
  );

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
        .filter((m): m is DatasetModel => m != null),
    [selectedModels, activeModels]
  );

  function handleSort(benchmarkId: string) {
    setSort((prev) => {
      if (prev?.benchmarkId === benchmarkId) {
        return { benchmarkId, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      const benchmark = activeBenchmarks.find((b) => b.id === benchmarkId);
      return {
        benchmarkId,
        // Default to the direction that puts the best score first.
        dir: benchmark?.higherIsBetter === false ? "asc" : "desc",
      };
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

  function handleCategoryFilter(next: BenchmarkCategory | null) {
    setCategoryFilter(next);
    // A column sort must never stay active after its column leaves the visible
    // category. Clearing is less surprising than retaining a hidden order.
    setSort(null);
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
    setShowModelsWithNoPublishedScores(false);
    setSort(null);
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
            dataStatus={dataStatus}
            officialUnavailableReason={officialUnavailableReason}
            officialArtifact={officialArtifact}
          />

          {view === "table" ? (
            <main id="main-content">
              {activeModels.length === 0 ? (
                <div className="glass-strong flex flex-col items-center justify-center gap-3 rounded-xl px-6 py-24 text-center">
                  <p className="text-lg font-semibold text-foreground">
                    Awaiting Official publication
                  </p>
                  <p className="text-sm text-muted-foreground max-w-md">
                    No benchmark claims are published in this build. Data will appear here only
                    after a governed Official release is approved and bundled.
                  </p>
                </div>
              ) : (
              <>
              <Filters
                search={search}
                onSearch={setSearch}
                vendors={vendors}
                vendorFilter={vendorFilter}
                onToggleVendor={toggleVendor}
                categoryFilter={categoryFilter}
                onCategory={handleCategoryFilter}
                openWeightsOnly={openWeightsOnly}
                onToggleOpenWeights={setOpenWeightsOnly}
                onClear={clearFilters}
                resultCount={sortedModels.length}
                hasModelsWithNoPublishedScores={hasModelsWithNoPublishedScores}
                showModelsWithNoPublishedScores={showModelsWithNoPublishedScores}
                onToggleModelsWithNoPublishedScores={setShowModelsWithNoPublishedScores}
              />
              <CategoryLeaders
                models={activeModels}
                benchmarks={activeBenchmarks}
                categoryFilter={categoryFilter}
                onOpenModel={openModel}
              />
              <Card className="glass-strong border-white/10 mb-3">
                <CardHeader>
                  <CardTitle className="text-base">Benchmark catalog</CardTitle>
                  <p className="text-xs text-muted-foreground">
                    Share of benchmarks per category.
                  </p>
                </CardHeader>
                <CardContent>
                  <Suspense
                    fallback={
                      <div role="status" className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
                        Loading chart…
                      </div>
                    }
                  >
                    <CatalogSharePie benchmarks={activeBenchmarks} />
                  </Suspense>
                </CardContent>
              </Card>
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
                <>
                <ScoreTable
                  models={sortedModels}
                  cohortModels={activeModels}
                  benchmarks={visibleBenchmarks}
                  sort={sort}
                  onSort={handleSort}
                  onBenchmarkClick={setSelectedBenchmarkId}
                  onOpenModel={openModel}
                  onClearSort={() => setSort(null)}
                  onToggleModelSelect={toggleModelSelect}
                  selectedModels={selectedModels}
                  rankMap={rankMap}
                  rankCohortTotal={activeBenchmarks.length}
                />
                {hiddenBenchmarkCount > 0 && (
                  <div className="flex justify-center py-3">
                    <button
                      type="button"
                      onClick={() => setShowAllBenchmarks(true)}
                      className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground"
                    >
                      Show all {categoryBenchmarks.length} benchmarks ({hiddenBenchmarkCount} hidden)
                    </button>
                  </div>
                )}
                {showAllBenchmarks && hiddenBenchmarkCount === 0 && categoryBenchmarks.length > 12 && (
                  <div className="flex justify-center py-3">
                    <button
                      type="button"
                      onClick={() => setShowAllBenchmarks(false)}
                      className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground"
                    >
                      Show fewer benchmarks
                    </button>
                  </div>
                )}
                </>
              )}
              </>
              )}
            </main>
          ) : (
            <main id="main-content">
              <Suspense
                fallback={
                  <div role="status" className="glass-strong flex items-center justify-center rounded-xl px-6 py-24 text-sm text-muted-foreground">
                    Loading comparison…
                  </div>
                }
              >
                <ModelComparison
                  models={selectedModelObjects}
                  benchmarks={activeBenchmarks}
                  allModels={activeModels}
                  onOpenModel={openModel}
                />
              </Suspense>
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
                  <Suspense
                    fallback={
                      <div role="status" className="flex items-center justify-center py-24 text-sm text-muted-foreground">
                        Loading benchmark…
                      </div>
                    }
                  >
                    <BenchmarkCard
                      benchmark={selectedBenchmark}
                      models={sortedModels}
                      cohortModels={activeModels}
                    />
                  </Suspense>
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
                  <Suspense
                    fallback={
                      <div role="status" className="flex items-center justify-center py-24 text-sm text-muted-foreground">
                        Loading model…
                      </div>
                    }
                  >
                    <ModelDetail
                      model={selectedModel}
                      models={sortedModels}
                      cohortModels={activeModels}
                      benchmarks={visibleBenchmarks}
                      selectedModels={selectedModels}
                      onToggleModelSelect={toggleModelSelect}
                    />
                  </Suspense>
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
