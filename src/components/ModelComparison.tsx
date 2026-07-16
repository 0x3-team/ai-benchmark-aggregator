import { useMemo, useState } from "react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { radarAverages, categoryLeader } from "../lib/aggregate";
import { RadarChart, RADAR_CATEGORIES, type RadarSeries } from "./RadarChart";
import { ScoreHeatmap } from "./ScoreHeatmap";
import { BenchmarkBars } from "./BenchmarkBars";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { modelColor } from "@/lib/palette";
import { cn } from "@/lib/utils";
import {
  formatContextWindow,
  formatOpenWeights,
  formatPricePair,
} from "@/lib/metadata";

interface ModelComparisonProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  onOpenModel: (modelId: string) => void;
}

export function ModelComparison({ models, benchmarks, onOpenModel }: ModelComparisonProps) {
  const { getValue } = useDataset();
  const allSeries: RadarSeries[] = useMemo(
    () =>
      models.map((m, i) => ({
        modelId: m.id,
        name: m.name,
        color: modelColor(i),
        points: radarAverages(m.id, benchmarks, getValue),
      })),
    [models, benchmarks, getValue]
  );

  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);

  const visibleSeries = allSeries.filter((s) => !hidden.has(s.modelId));

  const leaders = useMemo(
    () => categoryLeader(models, benchmarks, getValue),
    [models, benchmarks, getValue]
  );
  const leadsByModel = useMemo(() => {
    const map: Record<string, number> = {};
    for (const leader of leaders) {
      if (leader.modelId) {
        map[leader.modelId] = (map[leader.modelId] ?? 0) + 1;
      }
    }
    return map;
  }, [leaders]);

  function toggleSeries(id: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (models.length === 0) {
    return (
      <div className="glass-strong flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-16 text-center">
        <p className="text-sm font-medium text-foreground">
          No models selected
        </p>
        <p className="text-xs text-muted-foreground">
          Pick up to 6 models from the leaderboard to compare them here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="glass-strong border-white/10">
        <CardHeader>
          <CardTitle className="text-base">Capability radar</CardTitle>
          <p className="text-xs text-muted-foreground">
            Average normalized score per category (0–100%). Hover a label to
            highlight a model; click to hide/show it.
          </p>
        </CardHeader>
        <CardContent>
          <div className="mx-auto w-full max-w-[620px]">
            <RadarChart series={visibleSeries} activeId={activeId} />
          </div>
          <ul className="mt-4 flex flex-wrap justify-center gap-x-4 gap-y-2">
            {allSeries.map((s) => {
              const off = hidden.has(s.modelId);
              const active = activeId === s.modelId;
              const incomplete = s.points.some(
                (point) => RADAR_CATEGORIES.includes(point.category) && point.value === null
              );
              return (
                <li key={s.modelId}>
                  <button
                    type="button"
                    onClick={() => toggleSeries(s.modelId)}
                    onMouseEnter={() => setActiveId(s.modelId)}
                    onMouseLeave={() => setActiveId(null)}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-1.5 py-0.5 text-sm transition-opacity focus:outline-none focus:ring-2 focus:ring-ring",
                      off && "opacity-40"
                    )}
                  >
                    <span
                      className={cn(
                        "inline-block h-3 w-3 rounded-sm transition-shadow",
                        active && !off && "ring-2 ring-white/40"
                      )}
                      style={{
                        background: s.color,
                        boxShadow: off ? "none" : `0 0 8px ${s.color}`,
                      }}
                    />
                    <span>{s.name}</span>
                    {incomplete ? (
                      <span className="text-[10px] text-muted-foreground">Incomplete profile</span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <Card className="glass-strong border-white/10">
        <CardHeader>
          <CardTitle className="text-base">By category</CardTitle>
          <p className="text-xs text-muted-foreground">
            Stacked per-category averages across selected models.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2.5">
            {CATEGORIES.map((cat) => (
              <div
                key={cat}
                className="grid grid-cols-[90px_1fr] items-center gap-3"
              >
                <span className="text-xs text-muted-foreground">
                  {CATEGORY_LABELS[cat]}
                </span>
                <div className="flex flex-col gap-1">
                  {visibleSeries.map((s) => {
                    const p = s.points.find((pp) => pp.category === cat);
                    const v = p?.value ?? null;
                    const dim = activeId != null && activeId !== s.modelId;
                    const unavailable = v === null;
                    const pct = unavailable ? null : Math.round(v * 100);
                    return (
                      <div
                        key={s.modelId}
                        className={cn(
                          "relative h-3.5 rounded-sm bg-white/5 transition-opacity",
                          dim && "opacity-30"
                        )}
                        title={unavailable ? `${s.name}: no category data` : `${s.name}: ${pct}%`}
                        aria-label={unavailable ? `${s.name}: no category data` : `${s.name}: ${pct}%`}
                      >
                        {unavailable ? (
                          <div className="h-full rounded-sm border border-dashed border-white/20" />
                        ) : (
                          <div
                            className="h-full rounded-sm transition-[width] duration-300"
                            style={{
                              width: `${Math.max(v * 100, 2)}%`,
                              background: s.color,
                            }}
                          />
                        )}
                        <span className="absolute right-1 top-1/2 -translate-y-1/2 font-mono text-[10px] text-foreground/80">
                          {unavailable ? "—" : `${pct}%`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <ScoreHeatmap models={models} benchmarks={benchmarks} onOpenModel={onOpenModel} />

      <BenchmarkBars models={models} benchmarks={benchmarks} onOpenModel={onOpenModel} />

      <Card className="glass-strong border-white/10">
        <CardHeader>
          <CardTitle className="text-base">Specs comparison</CardTitle>
          <p className="text-xs text-muted-foreground">
            Click a model name to open its detail sheet.
          </p>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full border-separate border-spacing-0 text-[12px]">
              <thead>
                <tr>
                  <th className="sticky left-0 z-20 border-b border-white/10 bg-[rgba(13,18,28,0.94)] px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Spec
                  </th>
                  {models.map((m, i) => {
                    const leads = leadsByModel[m.id] ?? 0;
                    return (
                      <th
                        key={m.id}
                        className="min-w-[150px] border-b border-white/10 px-3 py-2 text-left"
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className="inline-block h-3 w-3 shrink-0 rounded-sm"
                            style={{ background: modelColor(i) }}
                          />
                          <button
                            type="button"
                            onClick={() => onOpenModel(m.id)}
                            className="text-left text-sm font-semibold text-foreground transition-colors hover:text-primary focus:outline-none focus:ring-2 focus:ring-ring"
                            title={`Open ${m.name}`}
                          >
                            {m.name}
                          </button>
                          {leads > 0 && (
                            <span className="ml-auto rounded-full bg-amber-400/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                              Leads in {leads}
                            </span>
                          )}
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    { label: "Vendor", get: (m: DatasetModel) => m.vendor },
                    {
                      label: "Params",
                      get: (m: DatasetModel) =>
                        m.paramsB == null ? "Not supplied" : `${m.paramsB}B`,
                    },
                    {
                      label: "Context",
                      get: (m: DatasetModel) => formatContextWindow(m.contextWindowK),
                    },
                    {
                      label: "Open weights",
                      get: (m: DatasetModel) => formatOpenWeights(m.openWeights),
                    },
                    {
                      label: "Price (in/out)",
                      get: (m: DatasetModel) =>
                        formatPricePair(m.priceInPer1M, m.priceOutPer1M),
                    },
                    {
                      label: "Modalities",
                      get: (m: DatasetModel) => m.modalities.join(", "),
                    },
                  ] as { label: string; get: (m: DatasetModel) => string }[]
                ).map((row, ri) => (
                  <tr
                    key={row.label}
                    className={cn(ri % 2 === 1 && "bg-white/[0.02]")}
                  >
                    <td className="sticky left-0 z-10 border-b border-white/5 bg-[rgba(13,18,28,0.94)] px-3 py-2 text-muted-foreground">
                      {row.label}
                    </td>
                    {models.map((m) => (
                      <td
                        key={m.id}
                        className="border-b border-white/5 px-3 py-2 font-medium text-foreground"
                      >
                        {row.get(m)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
