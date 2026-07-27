import { useMemo } from "react";
import { Plus, Check, Trophy } from "lucide-react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { columnStats, heatmapColor } from "../lib/color";
import { categoryLeader } from "../lib/aggregate";
import { CATEGORY_LABELS } from "../types";
import { categoryDotColor, categoryTint } from "../lib/categories";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { fmtScore } from "../lib/format";
import {
  formatContextWindow,
  formatOpenWeights,
  formatPricePair,
} from "../lib/metadata";
import { ClaimEvidence } from "./ClaimEvidence";
import { ModelScoreRadial } from "./charts/ModelScoreRadial";
import { ModelScoreProfileLine } from "./charts/ModelScoreProfileLine";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ModelDetailProps {
  model: DatasetModel;
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
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
  const { getValue, getScoreEntry } = useDataset();
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
  }, [models, benchmarks, getValue]);

  const leaders = useMemo(
    () => categoryLeader(models, benchmarks, getValue),
    [models, benchmarks, getValue]
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

      <ModelScoreRadial modelId={model.id} benchmarks={benchmarks} />

      <Card className="glass-strong border-white/10 mt-4">
        <CardHeader>
          <CardTitle className="text-base">Score profile vs field</CardTitle>
          <p className="text-xs text-muted-foreground">
            Model score vs benchmark average across all models.
          </p>
        </CardHeader>
        <CardContent>
          <ModelScoreProfileLine
            model={model}
            allModels={models}
            benchmarks={benchmarks}
          />
        </CardContent>
      </Card>

      <Separator className="my-4" />

      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Specs
      </h3>
      <div className="glass-inset grid grid-cols-2 gap-3 rounded-lg p-3 sm:grid-cols-3">
        <Spec label="Vendor" value={model.vendor} />
        <Spec label="Params" value={model.paramsB == null ? "Not supplied" : `${model.paramsB}B`} />
        <Spec label="Context" value={formatContextWindow(model.contextWindowK)} mono />
        <Spec label="Open" value={formatOpenWeights(model.openWeights)} />
        <Spec
          label="Price (in/out)"
          value={formatPricePair(model.priceInPer1M, model.priceOutPer1M)}
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
          const claim = entry?.officialProvenance ? entry : null;
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
                {claim ? (
                  <span className="truncate text-[10px] text-muted-foreground/70">
                    Governed claim evidence available
                  </span>
                ) : null}
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
              <ClaimEvidence
                entry={claim}
                modelName={model.name}
                benchmarkName={b.fullName}
              />
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
