import type { BenchmarkCategory } from "../types";
import { CATEGORY_LABELS } from "../types";
import type { RadarPoint } from "../lib/aggregate";

export interface RadarSeries {
  modelId: string;
  name: string;
  color: string;
  points: RadarPoint[];
}

interface RadarChartProps {
  series: RadarSeries[];
  size?: number;
  activeId?: string | null;
}

const ORDER: BenchmarkCategory[] = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
];

export function RadarChart({ series, size = 420, activeId = null }: RadarChartProps) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 54;
  const axes = ORDER.length;

  const angleFor = (i: number) => (Math.PI * 2 * i) / axes - Math.PI / 2;
  const pointFor = (i: number, r: number) => {
    const a = angleFor(i);
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r] as const;
  };

  const gridRings = [0.25, 0.5, 0.75, 1];

  return (
    <svg
      className="h-auto w-full"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Radar chart of benchmark categories"
    >
      {gridRings.map((ring) => (
        <polygon
          key={ring}
          className="fill-none stroke-white/15"
          points={ORDER.map((_, i) => pointFor(i, radius * ring).join(",")).join(" ")}
        />
      ))}

      {ORDER.map((cat, i) => {
        const [x, y] = pointFor(i, radius);
        const [lx, ly] = pointFor(i, radius + 22);
        const anchor =
          Math.abs(lx - cx) < 4 ? "middle" : lx > cx ? "start" : "end";
        return (
          <g key={cat}>
            <line className="stroke-white/10" x1={cx} y1={cy} x2={x} y2={y} />
            <text
              className="fill-muted-foreground text-[11px]"
              x={lx}
              y={ly}
              textAnchor={anchor}
              dominantBaseline="middle"
            >
              {CATEGORY_LABELS[cat]}
            </text>
          </g>
        );
      })}

      {series.map((s) => {
        const pts = ORDER.map((cat, i) => {
          const p = s.points.find((pp) => pp.category === cat);
          const v = p?.value ?? 0;
          return pointFor(i, radius * v).join(",");
        }).join(" ");
        const isActive = activeId != null && s.modelId === activeId;
        const isDim = activeId != null && s.modelId !== activeId;
        const fillOpacity = isActive ? 0.18 : 0;
        const strokeWidth = isActive ? 3 : 2;
        const opacity = isDim ? 0.3 : 1;
        return (
          <polygon
            key={s.modelId}
            points={pts}
            fill={s.color}
            fillOpacity={fillOpacity}
            stroke={s.color}
            strokeWidth={strokeWidth}
            strokeLinejoin="round"
            style={{ opacity }}
          />
        );
      })}
    </svg>
  );
}
