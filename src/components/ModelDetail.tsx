import { useMemo } from "react";
import { Plus, Check, Trophy } from "lucide-react";
import type { Benchmark, Model } from "../types";
import { getValue, getScoreEntry } from "../data/registry";
import { columnStats, heatmapColor } from "../lib/color";
import { categoryLeader } from "../lib/aggregate";
import { CATEGORY_LABELS } from "../types";
import { categoryDotColor, categoryTint } from "../lib/categories";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { fmtScore } from "../lib/format";

interface ModelDetailProps {
  model: Model;
  models: Model[];
  benchmarks: Benchmark[];
  selectedModels: string[];
  onToggleModelSelect: (id: string) => void;
}

export function ModelDetail({
  model,
  models,
  benchmarks,
  selectedModels,
  onToggleModelSelect,
}: ModelDetailProps) {
  const selected = selectedModels.includes(model.id);

  const statsByBench = useMemo(() => {
    const map: Record<string, ReturnType<typeof columnStats>> = {};
    for (const b of benchmarks) {
      map[b.id] = columnStats(
        models.map((m) => getValue(m.id, b.id)),
        b
      );
    }
    return map;
  }, [models, benchmarks]);

  const leaders = useMemo(
    () => categoryLeader(models, benchmarks),
    [models, benchmarks]
  );
  const leadsCats = leaders
    .filter((l) => l.modelId === model.id)
    .map((l) => l.category);

  return (
    <div className="flex flex-col">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-semibold tracking-tight">{model.name}</h2>
          {model.openWeights && (
            <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
              Open weights
            </span>
          )}
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {model.vendor} · {model.family} · {model.releaseDate}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant={selected ? "default" : "glass"}
          size="sm"
          onClick={() => onToggleModelSelect(model.id)}
          className="gap-1.5"
        >
          {selected ? (
            <>
              <Check className="h-3.5 w-3.5" /> In comparison
            </>
          ) : (
            <>
              <Plus className="h-3.5 w-3.5" /> Add to comparison
            </>
          )}
        </Button>
        {model.modalities.map((mod) => (
          <Badge
            key={mod}
            variant="outline"
            className="border-white/10 bg-white/5 text-muted-foreground"
            onClick={(e) => e.preventDefault()}
          >
            {mod}
          </Badge>
        ))}
      </div>

      {leadsCats.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-amber-400/20 bg-amber-400/5 px-3 py-2">
          <Trophy className="h-4 w-4 text-amber-300" />
          <span className="text-xs font-medium text-amber-200">
            Leads in
          </span>
          {leadsCats.map((cat) => (
            <span
              key={cat}
              className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs"
              style={{ background: categoryTint(cat, 0.12) }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: categoryDotColor(cat) }}
              />
              {CATEGORY_LABELS[cat]}
            </span>
          ))}
        </div>
      )}

      <Separator className="my-4" />

      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Specs
      </h3>
      <div className="glass-inset grid grid-cols-2 gap-3 rounded-lg p-3 sm:grid-cols-3">
        <Spec label="Vendor" value={model.vendor} />
        <Spec label="Params" value={model.paramsB == null ? "—" : `${model.paramsB}B`} />
        <Spec label="Context" value={`${model.contextWindowK}k`} mono />
        <Spec label="Open" value={model.openWeights ? "yes" : "no"} />
        <Spec
          label="Price (in/out)"
          value={
            model.priceInPer1M == null
              ? "—"
              : `$${model.priceInPer1M}/${model.priceOutPer1M}`
          }
          mono
        />
        <Spec label="Modalities" value={model.modalities.join(", ")} />
      </div>

      <Separator className="my-4" />

      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Scores
      </h3>
      <div className="flex flex-col gap-1">
        {benchmarks.map((b) => {
          const v = getValue(model.id, b.id);
          const entry = getScoreEntry(model.id, b.id);
          const prov =
            entry &&
            (entry.officialSourceId || entry.scoreRaw || entry.captureStatus)
              ? entry
              : null;
          const stats = statsByBench[b.id];
          const isBest = v != null && stats.best != null && v === stats.best;
          const bg = heatmapColor(v, stats, b);
          const display = fmtScore(v, b.scaleMax);
          return (
            <div
              key={b.id}
              className="flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-white/5"
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: bg === "transparent" ? "transparent" : bg }}
              />
              <span className="flex flex-1 flex-col truncate">
                <span className="truncate text-sm text-foreground/90">
                  {b.name}
                </span>
                {prov && (
                  <span className="truncate font-mono text-[10px] text-muted-foreground/70">
                    source {prov.officialSourceId ?? "—"} · raw{" "}
                    {prov.scoreRaw ?? "—"}
                    {prov.captureStatus ? ` · ${prov.captureStatus}` : ""}
                  </span>
                )}
              </span>
              {isBest && (
                <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                  SOTA
                </span>
              )}
              <span
                className={cn(
                  "w-12 text-right font-mono text-sm font-semibold",
                  v == null ? "text-muted-foreground/50" : "text-foreground"
                )}
              >
                {display}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Spec({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={cn("text-sm font-medium", mono && "font-mono")}>
        {value}
      </span>
    </div>
  );
}
