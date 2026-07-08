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
}: FiltersProps) {
  return (
    <div className="glass mb-3 flex flex-wrap items-center gap-3 rounded-xl px-4 py-3">
      <div className="relative min-w-[200px] flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          className="h-9 w-full rounded-lg border border-white/10 bg-white/5 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/40"
          type="search"
          placeholder="Search models, vendors, families…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Vendor
        </span>
        <div className="flex flex-wrap gap-1.5">
          {vendors.map((v) => (
            <Badge
              key={v}
              variant={vendorFilter.has(v) ? "default" : "ghost"}
              onClick={() => onToggleVendor(v)}
              className={cn(
                !vendorFilter.has(v) &&
                  "border-white/10 bg-white/5 text-muted-foreground"
              )}
            >
              {v}
            </Badge>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Category
        </span>
        <div className="flex flex-wrap gap-1.5">
          <Badge
            variant={categoryFilter === null ? "default" : "ghost"}
            onClick={() => onCategory(null)}
            className={cn(
              categoryFilter === null
                ? ""
                : "border-white/10 bg-white/5 text-muted-foreground"
            )}
          >
            All
          </Badge>
          {CATEGORIES.map((c) => (
            <Badge
              key={c}
              onClick={() => onCategory(c)}
              className={cn(
                "transition-colors",
                categoryFilter === c
                  ? "border-transparent bg-[hsl(258_90%_66%)] text-white hover:bg-[hsl(258_90%_72%)]"
                  : "border-white/10 bg-white/5 text-muted-foreground hover:text-foreground"
              )}
            >
              {CATEGORY_LABELS[c]}
            </Badge>
          ))}
        </div>
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
        <Switch
          checked={openWeightsOnly}
          onCheckedChange={onToggleOpenWeights}
        />
        Open weights only
      </label>

      <Button variant="ghost" size="sm" onClick={onClear} className="gap-1.5">
        <RotateCcw className="h-3.5 w-3.5" />
        Reset
      </Button>
      <span className="ml-auto font-mono text-xs text-muted-foreground">
        {resultCount} models
      </span>
    </div>
  );
}
