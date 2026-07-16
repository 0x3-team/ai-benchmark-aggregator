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

export const RADAR_CATEGORIES: readonly BenchmarkCategory[] = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
] as const;

export function RadarChart({ series, size = 420, activeId = null }: RadarChartProps) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 54;
  const axes = RADAR_CATEGORIES.length;

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
          points={RADAR_CATEGORIES.map((_, i) => pointFor(i, radius * ring).join(",")).join(" ")}
        />
      ))}

      {RADAR_CATEGORIES.map((cat, i) => {
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
        const values = RADAR_CATEGORIES.map(
          (cat) => s.points.find((point) => point.category === cat)?.value ?? null
        );
        if (!values.every((value): value is number => value !== null)) {
          return (
            <g key={s.modelId} data-radar-series-unavailable={s.modelId}>
              <title>{`${s.name}: incomplete category data`}</title>
              <desc>{`${s.name}: incomplete category data; no radar polygon is drawn.`}</desc>
            </g>
          );
        }
        const pts = values.map((value, i) => {
          return pointFor(i, radius * value).join(",");
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
            data-radar-series={s.modelId}
          />
        );
      })}
    </svg>
  );
}
