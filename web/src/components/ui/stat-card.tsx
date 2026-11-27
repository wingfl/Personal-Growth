import { cn, pct } from "@/lib/utils";
import { Card } from "./card";

export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const step = 100 / (values.length - 1);
  const points = values
    .map((value, index) => `${(index * step).toFixed(2)},${(28 - (value / max) * 24).toFixed(2)}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={cn("h-7 w-full", className)} aria-hidden>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function StatCard({
  label,
  value,
  hint,
  delta,
  series,
  onClick,
}: {
  label: string;
  value: string | number;
  hint?: string;
  delta?: number | null;
  series?: number[];
  onClick?: () => void;
}) {
  const rising = typeof delta === "number" && delta > 0;
  const falling = typeof delta === "number" && delta < 0;
  return (
    <Card
      className={cn("p-5", onClick && "cursor-pointer transition-colors hover:bg-muted/40")}
      onClick={onClick}
    >
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="num text-3xl font-semibold tracking-tight">{value}</span>
        {typeof delta === "number" && (
          <span
            className={cn(
              "num text-xs font-medium",
              rising && "text-success",
              falling && "text-danger",
              !rising && !falling && "text-muted-foreground",
            )}
          >
            {pct(delta)}
          </span>
        )}
      </div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      {series && series.length > 1 && (
        <div className="mt-3 text-primary/70">
          <Sparkline values={series} />
        </div>
      )}
    </Card>
  );
}
