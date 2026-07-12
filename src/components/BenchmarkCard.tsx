import { ExternalLink } from "lucide-react";
import type { Benchmark, Model } from "../types";
import { getValue } from "../data/registry";
import { columnStats } from "../lib/color";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { CATEGORY_LABELS } from "../types";
import { fmtScore } from "../lib/format";

interface BenchmarkCardProps {
  benchmark: Benchmark;
  models: Model[];
}

export function BenchmarkCard({ benchmark, models }: BenchmarkCardProps) {
  const values = models.map((m) => getValue(m.id, benchmark.id));
  const stats = columnStats(values, benchmark);

  const ranked = models
    .map((m) => ({ m, v: getValue(m.id, benchmark.id) }))
    .filter((r) => r.v != null)
    .sort((a, b) =>
      benchmark.higherIsBetter ? b.v! - a.v! : a.v! - b.v!
    );

  const fmt = (v: number | null) => fmtScore(v, benchmark.scaleMax);

  return (
    <div className="flex flex-col">
      <div>
        <Badge
          className="border-transparent bg-[hsl(258_90%_66%)] text-white"
          onClick={(e) => e.preventDefault()}
        >
          {CATEGORY_LABELS[benchmark.category]}
        </Badge>
        <h2 className="mt-2 text-xl font-semibold tracking-tight">
          {benchmark.fullName}
        </h2>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {benchmark.name} · scale /{benchmark.scaleMax} ·{" "}
          {benchmark.higherIsBetter ? "higher is better" : "lower is better"}
        </p>
      </div>

      <p className="mt-4 text-sm leading-relaxed text-foreground/80">
        {benchmark.description}
      </p>

      <div className="mt-4 grid grid-cols-4 gap-2">
        {[
          { label: "Best", value: fmt(stats.best), tone: "text-emerald-300" },
          { label: "Avg", value: fmt(stats.avg), tone: "text-foreground" },
          { label: "Worst", value: fmt(stats.worst), tone: "text-amber-300" },
          { label: "Coverage", value: `${stats.count}/${models.length}`, tone: "text-foreground" },
        ].map((cell) => (
          <div
            key={cell.label}
            className="glass-inset rounded-lg px-2 py-2 text-center"
          >
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {cell.label}
            </div>
            <div className={`mt-1 font-mono text-base font-bold ${cell.tone} ${
              cell.label === "Coverage" ? "text-sm" : ""
            }`}>
              {cell.value}
            </div>
          </div>
        ))}
      </div>

      <Separator className="my-4" />

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Methodology
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-foreground/80">
          {benchmark.methodology}
        </p>
      </div>

      <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Top models
      </h3>
      <ol className="flex flex-col gap-1">
        {ranked.slice(0, 6).map((r, i) => (
          <li
            key={r.m.id}
            className="glass-inset flex items-center gap-3 rounded-lg px-3 py-2"
          >
            <span className="w-5 font-mono text-xs text-muted-foreground">
              {i + 1}
            </span>
            <span className="flex-1 text-sm font-medium">{r.m.name}</span>
            <span className="font-mono text-sm font-bold text-emerald-300">
              {fmt(r.v)}
            </span>
          </li>
        ))}
        {ranked.length === 0 && (
          <li className="text-sm text-muted-foreground">
            No data for current filters
          </li>
        )}
      </ol>

      <a
        className="mt-5 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
        href={benchmark.sourceUrl}
        target="_blank"
        rel="noreferrer"
      >
        View source <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}
