import { BookOpen } from "lucide-react";
import { benchmarks } from "../data/benchmarks";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
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
}

export function GlossaryDialog({ open, onOpenChange }: GlossaryDialogProps) {
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
            {CATEGORIES.length} capability areas. Hover a header in the
            leaderboard for a quick definition, or pick a category below.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-5">
          {CATEGORIES.map((cat) => {
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
