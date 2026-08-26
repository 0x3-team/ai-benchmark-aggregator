import { BookOpen } from "lucide-react";
import { CATEGORY_LABELS, categoriesForBenchmarks } from "../types";
import type { DatasetBenchmark } from "../data/dataset";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";

interface GlossaryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  benchmarks: readonly DatasetBenchmark[];
}

export function GlossaryDialog({ open, onOpenChange, benchmarks }: GlossaryDialogProps) {
  const categories = categoriesForBenchmarks(benchmarks).filter((category) =>
    benchmarks.some((benchmark) => benchmark.category === category)
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            About these benchmarks
          </DialogTitle>
          <DialogDescription>
            {benchmarks.length} evaluations across{" "}
            {categories.length} capability areas. Hover a header in the
            leaderboard for a quick definition, or pick a category below.
          </DialogDescription>
        </DialogHeader>

        <div className="glass-inset rounded-lg px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
          <strong className="text-foreground">Trust note:</strong> ranking
          averages and radar charts are presentation helpers only. Official
          claim mode (when enabled) surfaces source-backed ledger values and
          never stores UI aggregates as scientific results.
        </div>

        <div className="flex flex-col gap-5">
          {categories.map((cat) => {
            const items = benchmarks.filter((b) => b.category === cat);
            if (items.length === 0) return null;
            return (
              <section key={cat}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-primary">
                  {CATEGORY_LABELS[cat]}
                </h3>
                <ul className="flex flex-col gap-2">
                  {items.map((b) => (
                    <li key={b.id} className="glass-inset rounded-lg px-3 py-2.5">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-semibold">
                          {b.fullName}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                          /{b.scaleMax}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {b.description}
                      </p>
                    </li>
                  ))}
                </ul>
                <Separator className="mt-3" />
              </section>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
