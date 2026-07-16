import { useMemo } from "react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { CATEGORY_COLORS, categoryTint } from "../lib/categories";
import { modelColor } from "../lib/palette";
import { cn } from "@/lib/utils";
import { ClaimEvidence } from "./ClaimEvidence";

interface BenchmarkBarsProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  onOpenModel: (modelId: string) => void;
}

export function BenchmarkBars({ models, benchmarks, onOpenModel }: BenchmarkBarsProps) {
  const { getValue, getScoreEntry } = useDataset();
  const colorById = useMemo(() => {
    const map: Record<string, string> = {};
    models.forEach((m, i) => (map[m.id] = modelColor(i)));
    return map;
  }, [models]);

  const groups = useMemo(
    () =>
      CATEGORIES.map((cat) => ({
        cat,
        items: benchmarks.filter((b) => b.category === cat),
      })).filter((g) => g.items.length > 0),
    [benchmarks]
  );

  return (
    <div className="glass-strong overflow-hidden rounded-xl">
      <div className="flex flex-col divide-y divide-white/5">
        {groups.map((g) => (
          <div key={g.cat} className="px-4 py-3">
            <div
              className="mb-2 flex items-center gap-2 rounded-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide"
              style={{
                background: categoryTint(g.cat, 0.12),
                color: CATEGORY_COLORS[g.cat],
              }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{
                  background: CATEGORY_COLORS[g.cat],
                  boxShadow: `0 0 6px ${CATEGORY_COLORS[g.cat]}`,
                }}
              />
              {CATEGORY_LABELS[g.cat]}
            </div>
            <div className="flex flex-col gap-2.5">
              {g.items.map((b) => {
                const scaleMax = b.scaleMax;
                return (
                  <div
                    key={b.id}
                    className="grid grid-cols-[140px_1fr] items-center gap-3"
                  >
                    <span
                      className="truncate text-xs text-muted-foreground"
                      title={b.fullName}
                    >
                      {b.name}
                    </span>
                    <div className="flex flex-col gap-1">
                      {models.map((m) => {
                        const v = getValue(m.id, b.id);
                        const entry = getScoreEntry(m.id, b.id);
                        const claim = entry?.officialProvenance ? entry : null;
                        const color = colorById[m.id];
                        const pct = v == null ? null : (v / scaleMax) * 100;
                        return (
                          <div
                            key={m.id}
                            className="relative h-3.5 rounded-sm bg-white/5"
                            title={
                              v == null
                                ? `${m.name}: no data`
                                : `${m.name}: ${pct!.toFixed(
                                    scaleMax === 10 ? 1 : 0
                                  )}%`
                            }
                          >
                            {pct == null ? (
                              <span className="absolute left-1 top-1/2 flex h-3.5 -translate-y-1/2 items-center">
                                <span className="h-0 w-10 border-t border-dashed border-white/30" />
                              </span>
                            ) : claim ? (
                              <ClaimEvidence
                                entry={claim}
                                modelName={m.name}
                                benchmarkName={b.fullName}
                                trigger={
                                  <button
                                    type="button"
                                    className={cn(
                                      "data-claim-evidence block h-full rounded-sm transition-[width] duration-300 focus:outline-none focus:ring-2 focus:ring-ring"
                                    )}
                                    style={{
                                      width: `${Math.max(pct, 2)}%`,
                                      background: color,
                                    }}
                                    aria-label={`View claim evidence for ${m.name} on ${b.fullName}`}
                                  />
                                }
                              />
                            ) : (
                              <button
                                type="button"
                                onClick={() => onOpenModel(m.id)}
                                className={cn(
                                  "block h-full rounded-sm transition-[width] duration-300 focus:outline-none focus:ring-2 focus:ring-ring"
                                )}
                                style={{
                                  width: `${Math.max(pct, 2)}%`,
                                  background: color,
                                }}
                                aria-label={
                                  v == null
                                    ? `${m.name}: no data`
                                    : `${m.name}: ${pct!.toFixed(
                                        scaleMax === 10 ? 1 : 0
                                      )}%`
                                }
                              />
                            )}
                            {pct != null && (
                              <span className="absolute right-1 top-1/2 -translate-y-1/2 font-mono text-[10px] text-foreground/80">
                                {pct.toFixed(scaleMax === 10 ? 1 : 0)}%
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
