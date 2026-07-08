import { useMemo } from "react";
import type { Benchmark, Model } from "../types";
import { categoryLeader } from "../lib/aggregate";
import { categoryDotColor, categoryTint } from "../lib/categories";
import { CATEGORY_LABELS } from "../types";
import { cn } from "@/lib/utils";

interface CategoryLeadersProps {
  models: Model[];
  benchmarks: Benchmark[];
  onOpenModel: (modelId: string) => void;
}

export function CategoryLeaders({
  models,
  benchmarks,
  onOpenModel,
}: CategoryLeadersProps) {
  const leaders = useMemo(
    () => categoryLeader(models, benchmarks),
    [models, benchmarks]
  );

  if (leaders.length === 0) return null;

  return (
    <div className="glass mb-3 rounded-xl px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Category leaders
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/70">
          top model per capability area
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {leaders.map((leader) => {
          const model = models.find((m) => m.id === leader.modelId);
          const name = model?.name ?? leader.modelId;
          const color = categoryDotColor(leader.category);
          return (
            <button
              key={leader.category}
              type="button"
              onClick={() => onOpenModel(leader.modelId)}
              className={cn(
                "group flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-left transition-colors hover:border-white/25 hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-ring"
              )}
              style={{ background: categoryTint(leader.category, 0.07) }}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: color, boxShadow: `0 0 8px ${color}` }}
              />
              <span className="flex flex-col leading-tight">
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  {CATEGORY_LABELS[leader.category]}
                </span>
                <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
                  {name}
                  <span className="font-mono text-[11px] text-emerald-300">
                    {Math.round(leader.avg * 100)}%
                  </span>
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
