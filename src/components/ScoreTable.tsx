import { useEffect, useMemo, useRef, useState } from "react";
import { Info, ArrowUp, ArrowDown, X } from "lucide-react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { columnStats, heatmapColor } from "../lib/color";
import {
  bestModelId,
  RANK_COVERAGE_THRESHOLD,
  type RankRow,
} from "../lib/aggregate";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { CATEGORY_COLORS, categoryTint } from "../lib/categories";
import { fmtScore as fmt } from "../lib/format";
import { STICKY_BG, GROUP_H, ROW_H, ROW_BUFFER, BODY_MAX_H } from "../lib/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  PopoverClose,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  ClaimEvidence,
  ClaimEvidenceDetails,
  ExternalSourceLink,
} from "./ClaimEvidence";

const TABLE_CHROME_H = 180;

interface ScoreTableProps {
  models: readonly DatasetModel[];
  /** The immutable full cohort. `models` may be filtered and/or sorted. */
  cohortModels: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  sort: { benchmarkId: string | null; dir: "asc" | "desc" } | null;
  onSort: (benchmarkId: string) => void;
  onBenchmarkClick: (benchmarkId: string) => void;
  onOpenModel: (modelId: string) => void;
  onClearSort: () => void;
  onToggleModelSelect: (modelId: string) => void;
  selectedModels: string[];
  rankMap: Record<string, RankRow>;
  rankCohortTotal: number;
}

export function ScoreTable({
  models,
  cohortModels,
  benchmarks,
  sort,
  onSort,
  onBenchmarkClick,
  onOpenModel,
  onClearSort,
  onToggleModelSelect,
  selectedModels,
  rankMap,
  rankCohortTotal,
}: ScoreTableProps) {
  const { getValue, getScoreEntry } = useDataset();
  const statsByBench = useMemo(() => {
    const map: Record<string, ReturnType<typeof columnStats>> = {};
    for (const b of benchmarks) {
      const values = cohortModels.map((m) => getValue(m.id, b.id));
      map[b.id] = columnStats(values, b);
    }
    return map;
  }, [cohortModels, benchmarks, getValue]);

  const bestByBench = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const b of benchmarks) {
      map[b.id] = bestModelId(b.id, cohortModels, benchmarks, getValue);
    }
    return map;
  }, [benchmarks, cohortModels, getValue]);

  const modelName = (id: string | null) =>
    id ? cohortModels.find((m) => m.id === id)?.name ?? id : null;

  const groups = useMemo(
    () =>
      CATEGORIES.map((cat) => ({
        cat,
        items: benchmarks.filter((b) => b.category === cat),
      })).filter((g) => g.items.length > 0),
    [benchmarks]
  );

  const activeCol = sort?.benchmarkId ?? null;
  const sortBench = benchmarks.find((b) => b.id === activeCol) ?? null;
  const rankMinimumCovered = Math.ceil(rankCohortTotal * RANK_COVERAGE_THRESHOLD);
  const rankMissingPenalty = cohortModels.length + 1;
  const rankCoveragePercent = RANK_COVERAGE_THRESHOLD * 100;
  const rankPolicy = `Overall presentation ranks are UI-only. Eligibility requires published scores for at least ${rankCoveragePercent}% of the immutable active comparable benchmark cohort: ${rankMinimumCovered} of ${rankCohortTotal} benchmarks. Each row shows its published-score coverage over that cohort. Each missing score counts as rank ${rankMissingPenalty}, one place below the ${cohortModels.length}-model cohort; filters only change visible rows.`;

  // --- Row virtualization -------------------------------------------------
  // Only render the rows inside (and a small buffer around) the vertical
  // viewport. The scroll container reports its scrollTop; we translate that
  // into a [start,end) window of model indices and pad the body with spacer
  // rows so the scrollbar reflects the true total row count. A fixed ROW_H
  // keeps the math O(1) and avoids per-row DOM measurement.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(BODY_MAX_H);

  // A new visible order, cohort, benchmark set, or dataset accessor
  // represents a new table coordinate system. Do not leave the user at an
  // old offset whose row identity no longer matches the viewport.
  const modelIdentity = useMemo(
    () => models.map((model) => model.id).join("\u001f"),
    [models]
  );
  const cohortIdentity = useMemo(
    () => cohortModels.map((model) => model.id).join("\u001f"),
    [cohortModels]
  );
  const benchmarkIdentity = useMemo(
    () => benchmarks.map((benchmark) => benchmark.id).join("\u001f"),
    [benchmarks]
  );

  useEffect(() => {
    if (scrollRef.current && scrollRef.current.scrollTop !== 0) {
      scrollRef.current.scrollTop = 0;
    }
    setScrollTop(0);
  }, [modelIdentity, cohortIdentity, benchmarkIdentity, getValue]);

  const totalRows = models.length;
  const comparisonLimit = 6;
  const comparisonLimitReached = selectedModels.length >= comparisonLimit;
  const bodyMaxH = Math.min(BODY_MAX_H, totalRows * ROW_H + TABLE_CHROME_H);
  const visibleH = Math.min(viewportH, bodyMaxH);
  const visibleCount = Math.ceil(visibleH / ROW_H) + ROW_BUFFER * 2;
  const requestedFirstIndex = Math.max(0, Math.floor(scrollTop / ROW_H) - ROW_BUFFER);
  const firstIndex = Math.min(
    Math.max(0, totalRows - visibleCount),
    requestedFirstIndex
  );
  const lastIndex = Math.min(totalRows, firstIndex + visibleCount);
  const visibleModels = models.slice(firstIndex, lastIndex);
  const topPad = firstIndex * ROW_H;
  const bottomPad = (totalRows - lastIndex) * ROW_H;

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    setScrollTop(el.scrollTop);
    if (el.clientHeight !== viewportH) setViewportH(el.clientHeight);
  }

  return (
    <div className="glass-strong overflow-hidden rounded-xl">
      {comparisonLimitReached && (
        <p
          id="comparison-limit-help"
          className="border-b border-white/10 px-3 py-2 text-xs text-muted-foreground"
        >
          Comparison limit reached: up to {comparisonLimit} models can be compared. Remove a selected model to choose another.
        </p>
      )}
      {sort?.benchmarkId && sortBench && (
        <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2 text-xs">
          <span className="text-muted-foreground">Sorted by</span>
          <span className="font-medium text-foreground">
            {sortBench?.name}
          </span>
          {sort.dir === "asc" ? (
            <ArrowUp className="h-3 w-3 text-primary" />
          ) : (
            <ArrowDown className="h-3 w-3 text-primary" />
          )}
          <button
            type="button"
            onClick={onClearSort}
            className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <X className="h-3 w-3" /> Clear
          </button>
        </div>
      )}

      <p
        id="overall-ranking-policy"
        className="border-b border-white/10 px-3 py-2 text-left text-[11px] leading-relaxed text-muted-foreground"
      >
        {rankPolicy}
      </p>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-auto scroll-thin"
        style={{ maxHeight: bodyMaxH || undefined }}
      >
        <table
          className="min-w-max w-full border-separate border-spacing-0 text-[12px]"
          aria-rowcount={totalRows + 3}
          aria-describedby="overall-ranking-policy"
        >
          <caption className="sr-only">
            Official benchmark scores and coverage-adjusted presentation rankings.
          </caption>
          <thead>
            <tr>
              <th
                rowSpan={2}
                className="sticky left-0 top-0 z-40 border-b border-white/10 text-center align-middle font-mono text-[11px] text-muted-foreground"
                style={{
                  background: STICKY_BG,
                  width: 34,
                  minWidth: 34,
                  padding: "0",
                }}
              >
                <span
                  title={`Overall presentation rank; at least ${rankCoveragePercent}% cohort coverage required, with missing scores counted as rank ${rankMissingPenalty}`}
                >
                  #
                </span>
              </th>
              <th
                rowSpan={2}
                className="sticky z-40 border-b border-r border-white/10 text-left align-middle text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                style={{
                  left: 34,
                  background: STICKY_BG,
                  minWidth: 210,
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
                    <div className="flex items-center justify-center gap-1.5">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: color, boxShadow: `0 0 6px ${color}` }}
                      />
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/90">
                        {CATEGORY_LABELS[g.cat]}
                      </span>
                    </div>
                  </th>
                );
              })}
            </tr>
            <tr>
              {groups.flatMap((g) =>
                g.items.map((b) => {
                  const active = sort?.benchmarkId === b.id;
                  const color = CATEGORY_COLORS[g.cat];
                  const topModelId = bestByBench[b.id];
                  const topName = modelName(topModelId);
                  const topVal = topModelId
                    ? getValue(topModelId, b.id)
                    : null;
                  const topEntry = topModelId
                    ? getScoreEntry(topModelId, b.id)
                    : null;
                  const topClaim = topEntry?.officialProvenance ? topEntry : null;
                  return (
                    <th
                      key={b.id}
                      aria-sort={
                        active
                          ? sort!.dir === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                      className="sticky z-10 border-b border-white/10 p-0 align-bottom"
                      style={{
                        minWidth: 58,
                        top: GROUP_H,
                        borderTop: `2px solid ${color}`,
                      }}
                    >
                      <div className="flex flex-col items-center gap-0.5 px-1 pb-1.5 pt-2">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              onClick={() => onBenchmarkClick(b.id)}
                              className="rounded px-1 text-center text-[11px] font-semibold text-foreground/90 transition-colors hover:text-primary"
                              title="Open benchmark detail"
                            >
                              {b.name}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-xs">
                            <p className="font-semibold text-foreground">
                              {b.fullName}
                            </p>
                            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                              {b.description}
                            </p>
                          </TooltipContent>
                        </Tooltip>
                        <div className="flex items-center gap-0.5">
                          <Popover>
                            <PopoverTrigger asChild>
                              <button
                                type="button"
                                aria-label={`About ${b.fullName}`}
                                className="rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                              >
                                <Info className="h-3 w-3" />
                              </button>
                            </PopoverTrigger>
                            <PopoverContent align="start" className="w-80">
                              <p className="text-sm font-semibold text-foreground">
                                {b.fullName}
                              </p>
                              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                                {b.name} · scale /{b.scaleMax} ·{" "}
                                {b.higherIsBetter
                                  ? "higher is better"
                                  : "lower is better"}
                              </p>
                              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                                {b.description}
                              </p>
                              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                                <span className="font-medium text-foreground/80">
                                  Methodology:{" "}
                                </span>
                                {b.methodology}
                              </p>
                              {topName && topVal != null && (
                                <div className="mt-2 flex flex-col gap-2">
                                  <PopoverClose asChild>
                                    <button
                                      type="button"
                                      onClick={() => onOpenModel(topModelId!)}
                                      className="flex min-w-0 items-center justify-between rounded-md border border-white/10 bg-white/5 px-2 py-1.5 text-left transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-ring"
                                    >
                                      <span className="text-xs text-muted-foreground">
                                        Top model
                                      </span>
                                      <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                                        {topName}
                                        <span className="font-mono text-emerald-300">
                                          {fmt(topVal, b.scaleMax)}
                                        </span>
                                      </span>
                                    </button>
                                  </PopoverClose>
                                  <ClaimEvidenceDetails
                                    entry={topClaim}
                                    modelName={topName}
                                    benchmarkName={b.fullName}
                                  />
                                </div>
                              )}
                              <ExternalSourceLink
                                href={b.sourceUrl}
                                className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                              >
                                source ↗
                                <span className="sr-only"> (opens in a new tab)</span>
                              </ExternalSourceLink>
                            </PopoverContent>
                          </Popover>

                          <button
                            type="button"
                            aria-label={`Sort by ${b.fullName}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              onSort(b.id);
                            }}
                            className={cn(
                              "rounded p-0.5 transition-colors hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring",
                              active
                                ? "text-primary"
                                : "text-muted-foreground/60"
                            )}
                          >
                            {active ? (
                              sort!.dir === "asc" ? (
                                <ArrowUp className="h-3 w-3" />
                              ) : (
                                <ArrowDown className="h-3 w-3" />
                              )
                            ) : (
                              <ArrowDown className="h-3 w-3 opacity-40" />
                            )}
                          </button>
                        </div>
                      </div>
                    </th>
                  );
                })
              )}
            </tr>
          </thead>
          <tbody>
            {topPad > 0 && (
              <tr aria-hidden="true" style={{ height: topPad }}>
                <td colSpan={benchmarks.length + 2} style={{ padding: 0, border: "none" }} />
              </tr>
            )}
            {visibleModels.map((m, visibleIndex) => {
              const rank = rankMap[m.id];
              const selected = selectedModels.includes(m.id);
              const isTop = rank?.rank === 1;
              const rankLabel =
                rank?.rank != null
                  ? `Overall presentation rank ${rank.rank}; coverage ${rank.covered} of ${rank.total} benchmarks. Each missing score counts as rank ${rankMissingPenalty}.`
                  : rank
                    ? `Unranked: ${rank.covered} of ${rank.total} benchmarks have data. Each missing score counts as rank ${rankMissingPenalty}.`
                    : "Unranked: no presentation summary is available.";
              return (
                <tr
                  key={m.id}
                  aria-rowindex={firstIndex + visibleIndex + 3}
                  style={{ height: ROW_H }}
                  className={cn(
                    "transition-colors",
                    selected ? "bg-primary/10" : "hover:bg-white/[0.03]"
                  )}
                >
                  <td
                    className="sticky left-0 z-20 border-b border-white/5 text-center font-mono text-[11px] text-muted-foreground"
                    style={{
                      background: STICKY_BG,
                      width: 34,
                      minWidth: 34,
                      padding: "0",
                      height: ROW_H,
                      maxHeight: ROW_H,
                      overflow: "hidden",
                      boxSizing: "border-box",
                    }}
                  >
                    <span aria-hidden="true">{rank?.rank ?? "—"}</span>
                    <span className="sr-only">{rankLabel}</span>
                  </td>
                  <td
                    className="sticky z-20 border-b border-r border-white/10 text-left"
                    style={{
                      left: 34,
                      background: STICKY_BG,
                      padding: "4px 12px",
                      height: ROW_H,
                      maxHeight: ROW_H,
                      overflow: "hidden",
                      boxSizing: "border-box",
                      boxShadow: isTop
                        ? "inset 3px 0 0 0 rgba(251,191,36,0.7)"
                        : undefined,
                    }}
                  >
                    <label className="flex h-full min-w-0 cursor-pointer items-center gap-2 overflow-hidden">
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={comparisonLimitReached && !selected}
                        aria-disabled={comparisonLimitReached && !selected}
                        aria-describedby={
                          comparisonLimitReached && !selected
                            ? "comparison-limit-help"
                            : undefined
                        }
                        aria-label={`Select ${m.name} for comparison`}
                        onChange={() => onToggleModelSelect(m.id)}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      <span className="flex min-w-0 flex-1 flex-col overflow-hidden leading-tight">
                        <span
                          aria-hidden="true"
                          title={m.name}
                          className={cn(
                            "block truncate font-medium",
                            isTop ? "text-amber-200" : "text-foreground"
                          )}
                        >
                          {m.name}
                        </span>
                        <span className="sr-only">{m.name}</span>
                        <span className="flex min-w-0 items-center gap-1 truncate text-[10px] text-muted-foreground">
                          <span className="truncate" title={`${m.vendor} · ${m.family}`}>
                            {m.vendor} · {m.family}
                          </span>
                          {m.openWeights && (
                            <span className="rounded bg-emerald-500/20 px-1 font-mono text-emerald-300">
                              OW
                            </span>
                          )}
                        </span>
                        <span className="text-[10px] text-muted-foreground/70">
                          {rank?.covered ?? 0}/{rank?.total ?? rankCohortTotal} coverage
                        </span>
                      </span>
                    </label>
                  </td>
                  {benchmarks.map((b) => {
                    const v = getValue(m.id, b.id);
                    const entry = getScoreEntry(m.id, b.id);
                    const claim = entry?.officialProvenance ? entry : null;
                    const stats = statsByBench[b.id];
                    const isBest =
                      v != null && stats.best != null && v === stats.best;
                    const bg = heatmapColor(v, stats, b);
                    const active = activeCol === b.id;
                    return (
                      <td
                        key={b.id}
                        className={cn(
                          "relative border-b border-r border-white/5 text-center",
                          isBest && "sota-cell"
                        )}
                        style={{
                          background: bg,
                          boxShadow:
                            v == null
                              ? "inset 0 0 0 1px rgba(255,255,255,0.06)"
                              : undefined,
                          height: 30,
                          maxHeight: ROW_H,
                          overflow: "hidden",
                          padding: 0,
                        }}
                        title={
                          v == null
                            ? "No data"
                            : claim
                              ? `${m.name} · ${b.name}: claim evidence available`
                              : `${m.name} · ${b.name}: ${v}`
                        }
                      >
                        {active && (
                          <span className="pointer-events-none absolute inset-0 z-0 bg-primary/10" />
                        )}
                        <span
                          className={cn(
                            "relative z-10 text-[12.5px] font-semibold",
                            v == null
                              ? "text-muted-foreground/50"
                              : "text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.65)]"
                          )}
                        >
                          {fmt(v, b.scaleMax)}
                        </span>
                        <ClaimEvidence
                          entry={claim}
                          modelName={m.name}
                          benchmarkName={b.fullName}
                          className="absolute right-0.5 top-0.5 z-20"
                        />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {bottomPad > 0 && (
              <tr aria-hidden="true" style={{ height: bottomPad }}>
                <td colSpan={benchmarks.length + 2} style={{ padding: 0, border: "none" }} />
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="sticky bottom-0 z-30" style={{ background: STICKY_BG }}>
              <td
                className="sticky left-0 z-20 border-t-2 border-white/15 text-center font-mono text-[11px] text-muted-foreground"
                style={{ background: STICKY_BG, width: 34, minWidth: 34 }}
              />
              <td
                className="sticky border-t-2 border-white/15 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                style={{ left: 34, background: STICKY_BG, padding: "8px 12px" }}
              >
                Column best
              </td>
              {benchmarks.map((b) => {
                const bestId = bestByBench[b.id];
                const bestName = modelName(bestId);
                const display = fmt(statsByBench[b.id].best, b.scaleMax);
                const bestEntry = bestId ? getScoreEntry(bestId, b.id) : null;
                const bestClaim = bestEntry?.officialProvenance ? bestEntry : null;
                return (
                  <td
                    key={b.id}
                    className="relative border-t-2 border-white/15 p-0 text-center font-mono text-[12px] font-bold text-emerald-300"
                  >
                    {bestId ? (
                      <button
                        type="button"
                        onClick={() => onOpenModel(bestId)}
                        title={`View ${bestName} — best in column`}
                        className="w-full px-0 py-2 text-emerald-300 transition-colors hover:bg-white/5 hover:text-emerald-200 focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        {display}
                      </button>
                    ) : (
                      <span className="block py-2">{display}</span>
                    )}
                    {bestId && bestName ? (
                      <ClaimEvidence
                        entry={bestClaim}
                        modelName={bestName}
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
