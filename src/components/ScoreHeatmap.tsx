import { useMemo } from "react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { columnStats, heatmapColor } from "../lib/color";
import { computeRanking, bestModelId } from "../lib/aggregate";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { CATEGORY_COLORS, categoryTint } from "../lib/categories";
import { cn } from "@/lib/utils";
import { fmtScore as fmt } from "../lib/format";
import { STICKY_BG, GROUP_H } from "../lib/table";
import { ClaimEvidence } from "./ClaimEvidence";

interface ScoreHeatmapProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  onOpenModel: (modelId: string) => void;
}

export function ScoreHeatmap({ models, benchmarks, onOpenModel }: ScoreHeatmapProps) {
  const { getValue, getScoreEntry } = useDataset();
  const statsByBench = useMemo(() => {
    const map: Record<string, ReturnType<typeof columnStats>> = {};
    for (const b of benchmarks) {
      const values = models.map((m) => getValue(m.id, b.id));
      map[b.id] = columnStats(values, b);
    }
    return map;
  }, [models, benchmarks, getValue]);

  const bestByBench = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const b of benchmarks) map[b.id] = bestModelId(b.id, models, benchmarks, getValue);
    return map;
  }, [models, benchmarks, getValue]);

  const orderedRows = useMemo(() => {
    return computeRanking(models, benchmarks, getValue);
  }, [models, benchmarks, getValue]);

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
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full border-separate border-spacing-0 text-[12px]">
          <thead>
            <tr>
              <th
                rowSpan={2}
                className="sticky left-0 top-0 z-40 border-b border-white/10 text-left align-middle text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                style={{
                  background: STICKY_BG,
                  minWidth: 180,
                  padding: "6px 12px",
                }}
              >
                Model
              </th>
              {groups.map((g) => {
                const color = CATEGORY_COLORS[g.cat];
                return (
                  <th
                    key={g.cat}
                    colSpan={g.items.length}
                    className="sticky top-0 z-10 border-b border-white/10 px-1 text-center"
                    style={{
                      background: categoryTint(g.cat, 0.14),
                      borderBottom: `2px solid ${color}`,
                      height: GROUP_H,
                    }}
                  >
                    <span className="flex items-center justify-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-foreground/90">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: color, boxShadow: `0 0 6px ${color}` }}
                      />
                      {CATEGORY_LABELS[g.cat]}
                    </span>
                  </th>
                );
              })}
            </tr>
            <tr>
              {groups.flatMap((g) =>
                g.items.map((b) => (
                  <th
                    key={b.id}
                    className="sticky z-10 border-b border-white/10 p-0 align-bottom text-[11px] font-semibold text-foreground/90"
                    style={{
                      minWidth: 50,
                      top: GROUP_H,
                      borderTop: `2px solid ${CATEGORY_COLORS[g.cat]}`,
                    }}
                  >
                    <div className="px-1 pb-1.5 pt-2" title={b.fullName}>
                      {b.name}
                    </div>
                  </th>
                ))
              )}
            </tr>
          </thead>
          <tbody>
            {orderedRows.map(({ model: m, rank }) => {
              const isTop = rank === 1;
              return (
                <tr key={m.id} className="transition-colors hover:bg-white/[0.03]">
                  <td
                    className="sticky z-20 border-b border-r border-white/10 text-left"
                    style={{
                      left: 0,
                      background: STICKY_BG,
                      padding: "4px 12px",
                      boxShadow: isTop
                        ? "inset 3px 0 0 0 rgba(251,191,36,0.7)"
                        : undefined,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => onOpenModel(m.id)}
                      className="flex flex-col items-start text-left leading-tight focus:outline-none focus:ring-2 focus:ring-ring"
                      title={`Open ${m.name}`}
                    >
                      <span
                        className={cn(
                          "font-medium",
                          isTop ? "text-amber-200" : "text-foreground"
                        )}
                      >
                        {m.name}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {m.vendor} · {m.family}
                      </span>
                    </button>
                  </td>
                  {benchmarks.map((b) => {
                    const v = getValue(m.id, b.id);
                    const entry = getScoreEntry(m.id, b.id);
                    const claim = entry?.officialProvenance ? entry : null;
                    const stats = statsByBench[b.id];
                    const isBest = v != null && stats.best != null && v === stats.best;
                    const bg = heatmapColor(v, stats, b);
                    return (
                      <td
                        key={b.id}
                        className={cn(
                          "relative border-b border-r border-white/5 p-0 text-center",
                          isBest && "sota-cell"
                        )}
                        style={{
                          background: bg,
                          boxShadow:
                            v == null
                              ? "inset 0 0 0 1px rgba(255,255,255,0.06)"
                              : undefined,
                          height: 30,
                        }}
                        title={
                          v == null
                            ? `${m.name} · ${b.name}: no data`
                            : claim
                              ? `${m.name} · ${b.name}: claim evidence available`
                              : `${m.name} · ${b.name}: ${v}`
                        }
                      >
                        {claim ? (
                          <ClaimEvidence
                            entry={claim}
                            modelName={m.name}
                            benchmarkName={b.fullName}
                            trigger={
                              <button
                                type="button"
                                className="data-claim-evidence relative flex h-full w-full items-center justify-center px-1 py-1 text-[12.5px] font-semibold text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.65)] focus:outline-none focus:ring-2 focus:ring-ring"
                                aria-label={`View claim evidence for ${m.name} on ${b.fullName}`}
                              >
                                {fmt(v, b.scaleMax)}
                              </button>
                            }
                          />
                        ) : (
                          <span
                            className={cn(
                              "relative flex h-full w-full items-center justify-center px-1 py-1 text-[12.5px] font-semibold",
                              v == null
                                ? "text-muted-foreground/50"
                                : "text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.65)]"
                            )}
                            aria-label={
                              v == null
                                ? `${m.name} · ${b.name}: no data`
                                : `${m.name} · ${b.name}: ${v}`
                            }
                          >
                            {fmt(v, b.scaleMax)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td
                className="sticky left-0 z-20 border-t-2 border-white/15 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                style={{ background: STICKY_BG, padding: "8px 12px" }}
              >
                Column best
              </td>
              {benchmarks.map((b) => {
                const bestId = bestByBench[b.id];
                const display = fmt(statsByBench[b.id].best, b.scaleMax);
                const bestModel = bestId
                  ? models.find((model) => model.id === bestId) ?? null
                  : null;
                const bestEntry = bestId ? getScoreEntry(bestId, b.id) : null;
                const bestClaim = bestEntry?.officialProvenance ? bestEntry : null;
                return (
                  <td
                    key={b.id}
                    className="relative border-t-2 border-white/15 p-0 text-center font-mono text-[12px] font-bold"
                    style={{ color: "rgb(110,231,183)" }}
                  >
                    {bestId ? (
                      <button
                        type="button"
                        onClick={() => onOpenModel(bestId)}
                        title="View best model"
                        className="w-full px-0 py-2 text-emerald-300 transition-colors hover:bg-white/5 hover:text-emerald-200 focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        {display}
                      </button>
                    ) : (
                      <span className="block py-2">{display}</span>
                    )}
                    {bestModel ? (
                      <ClaimEvidence
                        entry={bestClaim}
                        modelName={bestModel.name}
                        benchmarkName={b.fullName}
                        className="absolute right-0.5 top-0.5 z-20"
                      />
                    ) : null}
                  </td>
                );
              })}
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-4 border-t border-white/10 px-3 py-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="sota-swatch" /> best in column (SOTA)
        </span>
        <span className="flex items-center gap-1.5">
          low
          <span
            className="h-2 w-24 rounded-full"
            style={{
              background:
                "linear-gradient(90deg, rgba(59,130,246,0.55), rgba(34,197,94,0.95))",
            }}
          />
          high
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-muted-foreground/50">—</span> no data
        </span>
      </div>
    </div>
  );
}
