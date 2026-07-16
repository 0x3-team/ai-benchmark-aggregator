import { useMemo, useState } from "react";
import type { BenchmarkCategory } from "./types";
import { models as demoModels } from "./data/models";
import { benchmarks as demoBenchmarks } from "./data/benchmarks";
import { getScores } from "./data/scores";
import {
  DatasetProvider,
  useDataset,
  type DatasetInput,
  type DatasetModel,
} from "./data/dataset";
import { loadOfficialData, type OfficialLoadResult } from "./data/official";
import { selectDataset } from "./data/dataSelection";
import { computeRanking, sortModels, type RankRow } from "./lib/aggregate";
import { Header } from "./components/Header";
import { Filters } from "./components/Filters";
import { ScoreTable } from "./components/ScoreTable";
import { BenchmarkCard } from "./components/BenchmarkCard";
import { CategoryLeaders } from "./components/CategoryLeaders";
import { ModelDetail } from "./components/ModelDetail";
import { ModelComparison } from "./components/ModelComparison";
import { GlossaryDialog } from "./components/GlossaryDialog";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
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
const DEMO_DATASET: DatasetInput = {
  models: demoModels,
  benchmarks: demoBenchmarks,
  scores: getScores(),
};

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
  return (
    <AppWithDataSources
      demoData={DEMO_DATASET}
      officialLoadResult={officialLoadResult}
    />
  );
}

/**
 * The production App supplies only the fixed containment loader above. This
 * exported seam lets UI tests exercise a previously verified published result
 * without giving the runtime a second artifact import or a fallback path.
 */
export function AppWithDataSources({
  demoData,
  officialLoadResult,
}: {
  demoData: DatasetInput;
  officialLoadResult: OfficialLoadResult;
}) {
  // The discriminated selection is intentionally above DatasetProvider: every
  // commit receives one matching mode label and immutable data snapshot. The
  // current loader returns the tracked unavailable artifact, so `official`
  // can never become selected without a later REL-05 release authorization.
  const [requestedDataMode, setRequestedDataMode] = useState<DataMode>("demo");
  const selection = useMemo(
    () => selectDataset(requestedDataMode, demoData, officialLoadResult),
    [requestedDataMode, demoData, officialLoadResult]
  );

  return (
    <AppErrorBoundary
      resetKey={selection.data}
      sourceLabel={DATA_MODE_LABEL[selection.mode]}
    >
      <DatasetProvider data={selection.data}>
        <AppContent
          dataMode={selection.mode}
          officialLoadResult={selection.official}
          onRequestedDataModeChange={setRequestedDataMode}
        />
      </DatasetProvider>
    </AppErrorBoundary>
  );
}

interface AppContentProps {
  dataMode: DataMode;
  officialLoadResult: OfficialLoadResult;
  onRequestedDataModeChange: (mode: DataMode) => void;
}

function AppContent({
  dataMode,
  officialLoadResult,
  onRequestedDataModeChange,
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
  const [officialUnavailableAnnouncement, setOfficialUnavailableAnnouncement] = useState<string | null>(
    null
  );
  const [officialUnavailableAnnouncementId, setOfficialUnavailableAnnouncementId] = useState(0);
  const { toast } = useToast();

  const officialUnavailableReason =
    officialLoadResult.availability === "unavailable"
      ? officialLoadResult.reason
      : undefined;
  const officialArtifact =
    officialLoadResult.availability === "published"
      ? officialLoadResult.artifact
      : undefined;

  // Every data-dependent render reads the atomic provider snapshot selected
  // above this component. No handler can relabel a Demo snapshot as Official.
  const {
    models: activeModels,
    benchmarks: activeBenchmarks,
    getValue,
  } = useDataset();

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

  // The presentation cohort is the entire immutable dataset snapshot. Search,
  // vendor, category, and open-weights filters only control visible rows; they
  // cannot promote a partial or filtered model into an overall leader.
  const presentationRanking = useMemo(
    () => computeRanking(activeModels, activeBenchmarks, getValue),
    [activeModels, activeBenchmarks, getValue]
  );

  const sortedModels = useMemo(
    () =>
      sortModels(
        filteredModels,
        sort,
        visibleBenchmarks,
        activeBenchmarks,
        getValue,
        presentationRanking
      ),
    [
      filteredModels,
      sort,
      visibleBenchmarks,
      activeBenchmarks,
      getValue,
      presentationRanking,
    ]
  );

  const rankMap = useMemo(() => {
    const map: Record<string, RankRow> = {};
    presentationRanking.forEach((row) => (map[row.model.id] = row));
    return map;
  }, [presentationRanking]);

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
    setSort(null);
  }

  function resetDataDependentState() {
    // React batches this event's state work with the selected dataset change.
    // A future Official release may have different ids, categories, and
    // availability, so no old filter, sort, selection, or Compare view may
    // survive the trust-boundary transition.
    setView("table");
    clearFilters();
    setSelectedBenchmarkId(null);
    setSelectedModelId(null);
    setSelectedModels([]);
  }

  function handleDataModeChange(next: DataMode) {
    if (next === "official" && officialLoadResult.availability !== "published") {
      const message = `Official claims remain unavailable. ${officialLoadResult.reason} Visible data remains Demo (synthetic).`;
      setOfficialUnavailableAnnouncement(message);
      setOfficialUnavailableAnnouncementId((current) => current + 1);
      toast({ description: message });
      return;
    }
    if (next === dataMode) return;
    setOfficialUnavailableAnnouncement(null);
    onRequestedDataModeChange(next);
    resetDataDependentState();
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
            officialUnavailableReason={officialUnavailableReason}
            officialArtifact={officialArtifact}
            officialUnavailableAnnouncement={officialUnavailableAnnouncement}
            officialUnavailableAnnouncementId={officialUnavailableAnnouncementId}
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
                onCategory={handleCategoryFilter}
                openWeightsOnly={openWeightsOnly}
                onToggleOpenWeights={setOpenWeightsOnly}
                onClear={clearFilters}
                resultCount={sortedModels.length}
              />
              <CategoryLeaders
                models={activeModels}
                benchmarks={activeBenchmarks}
                categoryFilter={categoryFilter}
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
                  rankCohortTotal={activeBenchmarks.length}
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
