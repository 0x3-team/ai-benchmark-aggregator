import { Search, RotateCcw } from "lucide-react";
import type { BenchmarkCategory } from "../types";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface FiltersProps {
  search: string;
  onSearch: (s: string) => void;
  vendors: string[];
  vendorFilter: Set<string>;
  onToggleVendor: (v: string) => void;
  categoryFilter: BenchmarkCategory | null;
  onCategory: (c: BenchmarkCategory | null) => void;
  openWeightsOnly: boolean;
  onToggleOpenWeights: (v: boolean) => void;
  onClear: () => void;
  resultCount: number;
  hasModelsWithNoPublishedScores: boolean;
  showModelsWithNoPublishedScores: boolean;
  onToggleModelsWithNoPublishedScores: (show: boolean) => void;
}

export function Filters({
  search,
  onSearch,
  vendors,
  vendorFilter,
  onToggleVendor,
  categoryFilter,
  onCategory,
  openWeightsOnly,
  onToggleOpenWeights,
  onClear,
  resultCount,
  hasModelsWithNoPublishedScores,
  showModelsWithNoPublishedScores,
  onToggleModelsWithNoPublishedScores,
}: FiltersProps) {
  return (
    <div className="glass mb-3 flex flex-wrap items-center gap-3 rounded-xl px-4 py-3">
      <div className="relative min-w-[min(100%,200px)] flex-1 basis-full sm:basis-auto">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <label htmlFor="model-search" className="sr-only">
          Search models, vendors, and families
        </label>
        <input
          id="model-search"
          className="h-9 w-full rounded-lg border border-white/10 bg-white/5 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          type="search"
          placeholder="Search models, vendors, families…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>

      <fieldset className="flex min-w-0 items-start gap-2">
        <legend className="pt-1 text-[11px] font-medium uppercase tracking-wider text-slate-300">
          Vendor
        </legend>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Vendor filters">
          {vendors.map((v) => (
            <Badge
              key={v}
              interactive
              variant={vendorFilter.has(v) ? "default" : "ghost"}
              onClick={() => onToggleVendor(v)}
              aria-pressed={vendorFilter.has(v)}
              aria-label={`Filter by vendor ${v}`}
              className={cn(
                !vendorFilter.has(v) &&
                  "border-white/10 bg-white/5 text-slate-300"
              )}
            >
              {v}
            </Badge>
          ))}
        </div>
      </fieldset>

      <fieldset className="flex min-w-0 items-start gap-2">
        <legend className="pt-1 text-[11px] font-medium uppercase tracking-wider text-slate-300">
          Category
        </legend>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Category filters">
          <Badge
            interactive
            variant={categoryFilter === null ? "default" : "ghost"}
            onClick={() => onCategory(null)}
            aria-pressed={categoryFilter === null}
            aria-label="Show all categories"
            className={cn(
              categoryFilter === null
                ? ""
                : "border-white/10 bg-white/5 text-slate-300"
            )}
          >
            All
          </Badge>
          {CATEGORIES.map((c) => (
            <Badge
              key={c}
              interactive
              onClick={() => onCategory(c)}
              aria-pressed={categoryFilter === c}
              aria-label={`Filter by category ${CATEGORY_LABELS[c]}`}
              className={cn(
                "transition-colors",
                categoryFilter === c
                  ? "border-transparent bg-[hsl(258_90%_66%)] text-white hover:bg-[hsl(258_90%_72%)]"
                  : "border-white/10 bg-white/5 text-slate-300 hover:text-foreground"
              )}
            >
              {CATEGORY_LABELS[c]}
            </Badge>
          ))}
        </div>
      </fieldset>

      <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
        <Switch
          checked={openWeightsOnly}
          onCheckedChange={onToggleOpenWeights}
          aria-label="Open weights only"
        />
        Open weights only
      </label>

      {hasModelsWithNoPublishedScores ? (
        <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
          <Switch
            checked={showModelsWithNoPublishedScores}
            onCheckedChange={onToggleModelsWithNoPublishedScores}
            aria-label="Show models with no published scores"
          />
          Show models with no published scores
        </label>
      ) : null}

      <Button variant="ghost" size="sm" onClick={onClear} className="gap-1.5">
        <RotateCcw className="h-3.5 w-3.5" />
        Reset
      </Button>
      <span className="ml-auto font-mono text-xs text-slate-300" role="status" aria-live="polite" aria-atomic="true">
        {resultCount} models
      </span>
    </div>
  );
}
