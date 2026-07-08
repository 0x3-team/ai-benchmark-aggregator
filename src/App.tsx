import { useMemo, useState } from "react";
import type { BenchmarkCategory } from "./types";
import { models } from "./data/models";
import { benchmarks } from "./data/benchmarks";
import { computeRanking, sortModels } from "./lib/aggregate";
import { Header } from "./components/Header";
import { Filters } from "./components/Filters";
import { ScoreTable } from "./components/ScoreTable";
import { BenchmarkCard } from "./components/BenchmarkCard";
import { CategoryLeaders } from "./components/CategoryLeaders";
import { ModelDetail } from "./components/ModelDetail";
import { ModelComparison } from "./components/ModelComparison";
import { GlossaryDialog } from "./components/GlossaryDialog";
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

  const { toast } = useToast();

  const vendors = useMemo(
    () => [...new Set(models.map((m) => m.vendor))].sort(),
    []
  );

  const visibleBenchmarks = useMemo(
    () =>
      categoryFilter
        ? benchmarks.filter((b) => b.category === categoryFilter)
        : benchmarks,
    [categoryFilter]
  );

  const filteredModels = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
      if (vendorFilter.size > 0 && !vendorFilter.has(m.vendor)) return false;
      if (openWeightsOnly && !m.openWeights) return false;
      if (q) {
        const hay = `${m.name} ${m.vendor} ${m.family}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [search, vendorFilter, openWeightsOnly]);

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
    ? benchmarks.find((b) => b.id === selectedBenchmarkId) ?? null
    : null;

  const selectedModel = selectedModelId
    ? models.find((m) => m.id === selectedModelId) ?? null
    : null;

  const selectedModelObjects = useMemo(
    () =>
      selectedModels
        .map((id) => models.find((m) => m.id === id))
        .filter((m): m is (typeof models)[number] => m != null),
    [selectedModels]
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
            totalModels={models.length}
            totalBenchmarks={benchmarks.length}
            view={view}
            onViewChange={setView}
            selectedCount={selectedModels.length}
            onOpenGlossary={() => setGlossaryOpen(true)}
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
              <ModelComparison models={selectedModelObjects} onOpenModel={openModel} />
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

          <GlossaryDialog open={glossaryOpen} onOpenChange={setGlossaryOpen} />
        </div>
        <Toaster />
      </TooltipProvider>
  );
}
