import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ALL_CATEGORIES, CATEGORIES, type BenchmarkCategory } from "./types";
import {
  DatasetProvider,
  useDataset,
  type DatasetBenchmark,
  type DatasetModel,
} from "./data/dataset";
import { loadOfficialData, type OfficialLoadResult } from "./data/official";
import { selectOfficialDataset } from "./data/dataSelection";
import {
  computeRanking,
  modelsForComparisonClass,
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
import {
  createDefaultPermalinkState,
  decodePermalink,
  encodePermalink,
  PERMALINK_MAX_COMPARE,
  PERMALINK_MAX_VALUE_LENGTH,
  type PermalinkState,
} from "./lib/permalinkState";
import {
  benchmarksForComparisonClass,
  comparisonClassForCategory,
  type ComparisonClass,
} from "./lib/categories";

const PERMALINK_SYNC_DELAY_MS = 300;

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
  const previousSelectionKey = useRef(selection.key);
  const sourceChanged = previousSelectionKey.current !== selection.key;

  useEffect(() => {
    previousSelectionKey.current = selection.key;
  }, [selection.key]);

  return (
    <AppErrorBoundary
      resetKey={selection.data}
      sourceLabel="Official"
    >
      <DatasetProvider key={selection.key} data={selection.data}>
        <AppContent
          dataStatus={selection.status}
          officialLoadResult={selection.official}
          restorePermalinkFromLocation={!sourceChanged}
        />
      </DatasetProvider>
    </AppErrorBoundary>
  );
}

interface AppContentProps {
  dataStatus: "awaiting-publication" | "official";
  officialLoadResult: OfficialLoadResult;
  restorePermalinkFromLocation: boolean;
}

function readPermalinkState(): PermalinkState {
  if (typeof window === "undefined") return createDefaultPermalinkState();
  return decodePermalink(window.location.search);
}

function validatePermalinkState(
  state: PermalinkState,
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue?: (modelId: string, benchmarkId: string) => number | null
): PermalinkState {
  if (models.length === 0 && benchmarks.length === 0) {
    return createDefaultPermalinkState();
  }

  const modelIds = new Set(models.map((model) => model.id));
  const vendorNames = new Set(models.map((model) => model.vendor));
  const benchmarkById = new Map(
    benchmarks.map((benchmark) => [benchmark.id, benchmark] as const)
  );
  const availableCategories = new Set(
    benchmarks.map((benchmark) => benchmark.category)
  );
  const hasGeneralBenchmarks = benchmarks.some(
    (benchmark) => comparisonClassForCategory(benchmark.category) === "general"
  );
  const hasEmbeddingBenchmarks = benchmarks.some(
    (benchmark) => comparisonClassForCategory(benchmark.category) === "embedding"
  );
  const category =
    state.category && availableCategories.has(state.category)
      ? state.category
      : !hasGeneralBenchmarks && hasEmbeddingBenchmarks
        ? "embedding"
        : null;
  const selectedClass = category === "embedding" ? "embedding" : "general";
  const classBenchmarks = benchmarksForComparisonClass(benchmarks, selectedClass);
  const classModelIds = new Set(
    models
      .filter((model) =>
        getValue
          ? classBenchmarks.some((benchmark) => getValue(model.id, benchmark.id) != null)
          : true
      )
      .map((model) => model.id)
  );
  const sortBenchmark = state.sort
    ? benchmarkById.get(state.sort.benchmarkId)
    : undefined;
  const sort =
    state.sort &&
    sortBenchmark &&
    (category === "embedding"
      ? sortBenchmark.category === "embedding"
      : sortBenchmark.category !== "embedding" &&
        (category === null || sortBenchmark.category === category))
      ? state.sort
      : null;

  return {
    ...state,
    vendor: state.vendor.filter((vendor) => vendorNames.has(vendor)),
    category,
    sort,
    compare: state.compare.filter((modelId) => modelIds.has(modelId) && classModelIds.has(modelId)),
    model: state.model && modelIds.has(state.model) && classModelIds.has(state.model) ? state.model : null,
    benchmark:
      state.benchmark && benchmarkById.has(state.benchmark)
        ? ((category === "embedding" && benchmarkById.get(state.benchmark)?.category === "embedding") ||
            (category !== "embedding" && benchmarkById.get(state.benchmark)?.category !== "embedding"))
          ? state.benchmark
          : null
        : null,
    all: state.all && classBenchmarks.length > 12,
  };
}

function AppContent({
  dataStatus,
  officialLoadResult,
  restorePermalinkFromLocation,
}: AppContentProps) {
  const [glossaryOpen, setGlossaryOpen] = useState(false);
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

  const [permalinkState, setPermalinkState] = useState<PermalinkState>(() =>
    validatePermalinkState(
      restorePermalinkFromLocation
        ? readPermalinkState()
        : createDefaultPermalinkState(),
      activeModels,
      activeBenchmarks,
      getValue
    )
  );
  const {
    view,
    q: search,
    category: categoryFilter,
    open: openWeightsOnly,
    sort,
    benchmark: selectedBenchmarkId,
    model: selectedModelId,
    compare: selectedModels,
    all: showAllBenchmarks,
    zero: showModelsWithNoPublishedScores,
  } = permalinkState;
  const comparisonClass: ComparisonClass = comparisonClassForCategory(
    categoryFilter ?? "other"
  );
  const vendorFilter = useMemo(
    () => new Set(permalinkState.vendor),
    [permalinkState.vendor]
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const restoreFromLocation = () => {
      setPermalinkState(
        validatePermalinkState(
          decodePermalink(window.location.search),
          activeModels,
          activeBenchmarks,
          getValue
        )
      );
    };
    window.addEventListener("popstate", restoreFromLocation);
    return () => window.removeEventListener("popstate", restoreFromLocation);
  }, [activeBenchmarks, activeModels, getValue]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const searchString = encodePermalink(permalinkState);
    if (window.location.search === searchString) return;
    const timeoutId = window.setTimeout(() => {
      if (window.location.search === searchString) return;
      try {
        window.history.replaceState(
          window.history.state,
          "",
          `${window.location.pathname}${searchString}${window.location.hash}`
        );
      } catch {
        // Keep the current UI state if a browser rejects a History API write.
      }
    }, PERMALINK_SYNC_DELAY_MS);
    return () => window.clearTimeout(timeoutId);
  }, [permalinkState]);

  const vendors = useMemo(
    () => [...new Set(activeModels.map((m) => m.vendor))].sort(),
    [activeModels]
  );

  const categoryBenchmarks = useMemo(
    () =>
      categoryFilter === "embedding"
        ? benchmarksForComparisonClass(activeBenchmarks, "embedding")
        : categoryFilter
          ? activeBenchmarks.filter((b) => b.category === categoryFilter)
          : benchmarksForComparisonClass(activeBenchmarks, "general"),
    [categoryFilter, activeBenchmarks]
  );

  const comparisonBenchmarks = useMemo(
    () => benchmarksForComparisonClass(activeBenchmarks, comparisonClass),
    [activeBenchmarks, comparisonClass]
  );

  const hasGeneralBenchmarks = activeBenchmarks.some(
    (benchmark) => benchmark.category !== "embedding"
  );
  const hasEmbeddingBenchmarks = activeBenchmarks.some(
    (benchmark) => benchmark.category === "embedding"
  );
  const availableFilterCategories = useMemo(() => {
    if (!hasGeneralBenchmarks && hasEmbeddingBenchmarks) return ["embedding"] as const;
    return hasEmbeddingBenchmarks ? ALL_CATEGORIES : CATEGORIES;
  }, [hasGeneralBenchmarks, hasEmbeddingBenchmarks]);

  const comparisonModels = useMemo(
    () =>
      modelsForComparisonClass(
        activeModels,
        activeBenchmarks,
        getValue,
        comparisonClass
      ),
    [activeModels, activeBenchmarks, getValue, comparisonClass]
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
    return comparisonModels.filter((m) => {
      if (vendorFilter.size > 0 && !vendorFilter.has(m.vendor)) return false;
      if (openWeightsOnly && !m.openWeights) return false;
      if (q) {
        const hay = `${m.name} ${m.vendor} ${m.family}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [search, vendorFilter, openWeightsOnly, comparisonModels]);

  const filteredUnrankedModels = useMemo(() => {
    if (!showModelsWithNoPublishedScores || comparisonBenchmarks.length === 0) return [];
    const q = search.trim().toLowerCase();
    const hasClassScore = (model: DatasetModel) =>
      comparisonBenchmarks.some((benchmark) => getValue(model.id, benchmark.id) != null);
    return activeModels.filter((model) => {
      if (hasClassScore(model)) return false;
      if (vendorFilter.size > 0 && !vendorFilter.has(model.vendor)) return false;
      if (openWeightsOnly && !model.openWeights) return false;
      if (q && !`${model.name} ${model.vendor} ${model.family}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [showModelsWithNoPublishedScores, search, vendorFilter, openWeightsOnly, activeModels, comparisonBenchmarks, getValue]);

  // The presentation cohort is the complete active comparison-class snapshot.
  // Search, vendor, benchmark-category, and open-weights filters only control
  // visible rows; they cannot mix embedding and general-model rankings.
  const presentationRanking = useMemo(
    () =>
      computeRanking(
        comparisonModels,
        comparisonBenchmarks,
        getValue,
        comparisonBenchmarks
      ),
    [comparisonModels, comparisonBenchmarks, getValue]
  );

  const rankMap = useMemo(() => {
    const map: Record<string, RankRow> = {};
    presentationRanking.forEach((row) => (map[row.model.id] = row));
    return map;
  }, [presentationRanking]);

  const modelsWithPublishedScores = useMemo(
    () => filteredModels,
    [filteredModels]
  );

  const hasModelsWithNoPublishedScores = useMemo(
    () =>
      comparisonBenchmarks.length > 0 &&
      activeModels.some((model) =>
        comparisonBenchmarks.every((benchmark) => getValue(model.id, benchmark.id) == null)
      ),
    [activeModels, comparisonBenchmarks, getValue]
  );

  const sortedModels = useMemo(
    () =>
      sortModels(
        modelsWithPublishedScores,
        sort,
        visibleBenchmarks,
        comparisonBenchmarks,
        getValue,
        presentationRanking
      ),
    [
      modelsWithPublishedScores,
      sort,
      visibleBenchmarks,
      comparisonBenchmarks,
      getValue,
      presentationRanking,
    ]
  );

  const visibleModelCount = sortedModels.length + filteredUnrankedModels.length;
  const hasNoPublishedScoresInCohort =
    comparisonBenchmarks.length > 0 && comparisonModels.length === 0;

  const selectedBenchmark = selectedBenchmarkId
    ? comparisonBenchmarks.find((b) => b.id === selectedBenchmarkId) ?? null
    : null;

  const selectedModel = selectedModelId
    ? comparisonModels.find((m) => m.id === selectedModelId) ?? null
    : null;

  const selectedModelObjects = useMemo(
    () =>
      selectedModels
        .map((id) => comparisonModels.find((m) => m.id === id))
        .filter((m): m is DatasetModel => m != null),
    [selectedModels, comparisonModels]
  );

  function handleSort(benchmarkId: string) {
    setPermalinkState((previous) => {
      const nextSort =
        previous.sort?.benchmarkId === benchmarkId
          ? {
              benchmarkId,
              dir: previous.sort.dir === "asc" ? ("desc" as const) : ("asc" as const),
            }
          : {
              benchmarkId,
              // Default to the direction that puts the best score first.
              dir:
                activeBenchmarks.find((benchmark) => benchmark.id === benchmarkId)
                  ?.higherIsBetter === false
                  ? ("asc" as const)
                  : ("desc" as const),
            };
      return { ...previous, sort: nextSort };
    });
  }

  function toggleVendor(v: string) {
    setPermalinkState((previous) => {
      const vendor = previous.vendor.includes(v)
        ? previous.vendor.filter((candidate) => candidate !== v)
        : [...previous.vendor, v];
      return { ...previous, vendor };
    });
  }

  function focusCategoryControl(next: BenchmarkCategory | null) {
    if (typeof document === "undefined") return;
    const id = next === null ? "category-filter-all" : `category-filter-${next}`;
    window.setTimeout(() => document.getElementById(id)?.focus(), 0);
  }

  function handleCategoryFilter(next: BenchmarkCategory | null) {
    // A column sort must never stay active after its column leaves the visible
    // category. Clearing is less surprising than retaining a hidden order.
    setPermalinkState((previous) => ({
      ...previous,
      category: next,
      sort: null,
      all: next === null ? previous.all : false,
      ...(comparisonClassForCategory(previous.category ?? "other") !==
      comparisonClassForCategory(next ?? "other")
        ? { compare: [], model: null, benchmark: null, view: "table" as const }
        : {}),
    }));
    focusCategoryControl(next);
  }

  function toggleModelSelect(id: string) {
    if (selectedModels.includes(id)) {
      setPermalinkState((previous) => ({
        ...previous,
        compare: previous.compare.filter((candidate) => candidate !== id),
      }));
      toast({ description: "Removed from comparison" });
      return;
    }
    if (selectedModels.length >= PERMALINK_MAX_COMPARE) {
      toast({ description: "Comparison is full (max 6)" });
      return;
    }
    setPermalinkState((previous) => ({
      ...previous,
      compare: [...previous.compare, id],
    }));
    toast({
      description: `Added to comparison (${selectedModels.length + 1}/${PERMALINK_MAX_COMPARE})`,
    });
  }

  function clearFilters() {
    const hasGeneralClass = activeBenchmarks.some(
      (benchmark) => comparisonClassForCategory(benchmark.category) === "general"
    );
    setPermalinkState((previous) => ({
      ...previous,
      q: "",
      vendor: [],
      category: hasGeneralClass ? null : "embedding",
      open: false,
      zero: false,
      sort: null,
      compare: [],
      model: null,
      benchmark: null,
      view: "table",
    }));
  }

  function openModel(id: string) {
    setPermalinkState((previous) => ({
      ...previous,
      model: id,
      benchmark: null,
    }));
  }

  function openBenchmark(id: string) {
    setPermalinkState((previous) => ({
      ...previous,
      benchmark: id,
      model: null,
    }));
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
            onViewChange={(next) =>
              setPermalinkState((previous) => ({ ...previous, view: next }))
            }
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
              <p
                id="comparison-class-status"
                role="status"
                aria-live="polite"
                className="mb-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-xs text-slate-300"
              >
                <strong className="text-foreground">
                  {comparisonBenchmarks.length > 0
                    ? `${comparisonClass === "embedding" ? "Embeddings" : "General"} comparison class.`
                    : `${comparisonClass === "embedding" ? "Embeddings" : "General"} comparison class unavailable.`}
                </strong>{" "}
                {comparisonBenchmarks.length > 0
                  ? <>Rankings, coverage, and missing-score penalties use only the complete active{" "}
                    {comparisonClass === "embedding" ? "embedding" : "non-embedding"} benchmark cohort.</>
                  : <>No active {comparisonClass === "embedding" ? "embedding" : "non-embedding"} benchmarks are available.</>}
              </p>
              <Filters
                search={search}
                onSearch={(q) =>
                  setPermalinkState((previous) => ({
                    ...previous,
                    q: q.slice(0, PERMALINK_MAX_VALUE_LENGTH),
                  }))
                }
                vendors={vendors}
                vendorFilter={vendorFilter}
                onToggleVendor={toggleVendor}
                categoryFilter={categoryFilter}
                onCategory={handleCategoryFilter}
                availableCategories={availableFilterCategories}
                showAllCategories={hasGeneralBenchmarks}
                openWeightsOnly={openWeightsOnly}
                onToggleOpenWeights={(open) =>
                  setPermalinkState((previous) => ({ ...previous, open }))
                }
                onClear={clearFilters}
                resultCount={visibleModelCount}
                hasModelsWithNoPublishedScores={hasModelsWithNoPublishedScores}
                showModelsWithNoPublishedScores={showModelsWithNoPublishedScores}
                onToggleModelsWithNoPublishedScores={(zero) =>
                  setPermalinkState((previous) => ({ ...previous, zero }))
                }
              />
              <CategoryLeaders
                models={comparisonModels}
                benchmarks={comparisonBenchmarks}
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
                    <CatalogSharePie benchmarks={comparisonBenchmarks} />
                  </Suspense>
                </CardContent>
              </Card>
              {sortedModels.length === 0 && filteredUnrankedModels.length === 0 ? (
                <div className="glass-strong flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-16 text-center">
                  {hasNoPublishedScoresInCohort ? (
                    <>
                      <p className="text-sm font-medium text-foreground">
                        No published scores in this cohort
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Turn on “Show models with no published scores in this cohort” to view
                        unranked models.
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-medium text-foreground">
                        No models match your filters
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Try clearing the vendor, category, or open-weights filters.
                      </p>
                    </>
                  )}
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
                  cohortModels={comparisonModels}
                  benchmarks={visibleBenchmarks}
                  sort={sort}
                  onSort={handleSort}
                  onBenchmarkClick={openBenchmark}
                  onOpenModel={openModel}
                  onClearSort={() =>
                    setPermalinkState((previous) => ({ ...previous, sort: null }))
                  }
                  onToggleModelSelect={toggleModelSelect}
                  selectedModels={selectedModels}
                  rankMap={rankMap}
                  rankCohortTotal={comparisonBenchmarks.length}
                  unrankedModels={filteredUnrankedModels}
                  comparisonClassLabel={comparisonClass === "embedding" ? "Embeddings" : "General"}
                />
                {hiddenBenchmarkCount > 0 && (
                  <div className="flex justify-center py-3">
                    <button
                      type="button"
                      onClick={() =>
                        setPermalinkState((previous) => ({ ...previous, all: true }))
                      }
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
                      onClick={() =>
                        setPermalinkState((previous) => ({ ...previous, all: false }))
                      }
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
                  benchmarks={comparisonBenchmarks}
                  allModels={comparisonModels}
                  onOpenModel={openModel}
                />
              </Suspense>
            </main>
          )}

          <Sheet
            open={!!selectedBenchmark}
            onOpenChange={(o) => {
              if (!o) {
                setPermalinkState((previous) => ({ ...previous, benchmark: null }));
              }
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
                      cohortModels={comparisonModels}
                    />
                  </Suspense>
                </>
              )}
            </SheetContent>
          </Sheet>

          <Sheet
            open={!!selectedModel}
            onOpenChange={(o) => {
              if (!o) {
                setPermalinkState((previous) => ({ ...previous, model: null }));
              }
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
                      cohortModels={comparisonModels}
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
            benchmarks={comparisonBenchmarks}
          />
        </div>
        <Toaster />
      </TooltipProvider>
  );
}
