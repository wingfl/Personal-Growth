import { useMemo, useState } from "react";
import { Waypoints } from "lucide-react";
import { useApi, type CapabilitiesPayload, type GrowthPayload } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EChart } from "@/components/charts/EChart";
import { growthOption } from "@/lib/charts";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/states";
import { ITEM_TYPE_LABEL as TYPE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

type TrendPayload = { weeks: { week_start: string; label: string; count: number }[]; total: number };
type MixRow = { key: string; count: number };
type MixPayload = { total: number; by_type: MixRow[]; by_domain: MixRow[] };
type HeatPayload = { weeks: number; max: number; cells: { week_start: string; weekday: number; count: number }[] };


const RANGES = [
  { key: "12", label: "近 12 周" },
  { key: "26", label: "近 26 周" },
  { key: "52", label: "近一年" },
];

export function Insights() {
  const [range, setRange] = useState("26");
  const growth = useApi<GrowthPayload>("/api/growth?months=12");
  const caps = useApi<CapabilitiesPayload>("/api/capabilities");
  const trend = useApi<TrendPayload>(`/api/insights/trend?weeks=${range}`);
  const mix = useApi<MixPayload>("/api/insights/mix");
  const heat = useApi<HeatPayload>(`/api/insights/heatmap?weeks=${range}`);

  const trendOption = useMemo(() => {
    const weeks = trend.data?.weeks ?? [];
    const moving = weeks.map((_, index) => {
      const window = weeks.slice(Math.max(0, index - 3), index + 1);
      return Math.round((window.reduce((sum, point) => sum + point.count, 0) / window.length) * 10) / 10;
    });
    return {
      grid: { left: 8, right: 12, top: 30, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 12 } },
      xAxis: {
        type: "category",
        data: weeks.map((point) => point.label),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "rgba(128,128,128,.35)" } },
        axisLabel: { fontSize: 10, interval: weeks.length > 20 ? 3 : weeks.length > 12 ? 1 : 0 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(128,128,128,.15)" } },
        axisLabel: { fontSize: 12, color: "#71717a" },
      },
      series: [
        {
          name: "每周事项",
          type: "bar",
          data: weeks.map((point) => point.count),
          barMaxWidth: 16,
          itemStyle: { color: "#4f46e5", borderRadius: [3, 3, 0, 0] },
        },
        {
          name: "4 周移动平均",
          type: "line",
          data: moving,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#0d9488", width: 2 },
        },
      ],
    };
  }, [trend.data]);

  const mixOption = useMemo(() => {
    const rows = (mix.data?.by_type ?? []).slice(0, 8).reverse();
    return {
      grid: { left: 8, right: 24, top: 8, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "rgba(128,128,128,.15)" } }, axisLabel: { fontSize: 12 } },
      yAxis: {
        type: "category",
        data: rows.map((row) => TYPE_LABEL[row.key] ?? row.key),
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { fontSize: 12, color: "#71717a" },
      },
      series: [
        {
          type: "bar",
          data: rows.map((row) => row.count),
          barMaxWidth: 14,
          itemStyle: { color: "#0d9488", borderRadius: [0, 4, 4, 0] },
        },
      ],
    };
  }, [mix.data]);

  const heatOption = useMemo(() => {
    const cells = heat.data?.cells ?? [];
    const weekStarts = Array.from(new Set(cells.map((cell) => cell.week_start)));
    const index = new Map(weekStarts.map((week, position) => [week, position]));
    const data = cells.map((cell) => [index.get(cell.week_start) ?? 0, cell.weekday, cell.count]);
    const max = Math.max(heat.data?.max ?? 1, 1);
    return {
      grid: { left: 8, right: 8, top: 8, bottom: 24, containLabel: true },
      tooltip: {
        formatter: (params: { value: [number, number, number] }) => {
          const [weekIndex, weekday, count] = params.value;
          return `${weekStarts[weekIndex]} 周${"一二三四五六日"[weekday]}：${count} 条`;
        },
      },
      xAxis: {
        type: "category",
        data: weekStarts.map((week) => week.slice(5)),
        splitArea: { show: false },
        axisTick: { show: false },
        axisLabel: { fontSize: 10, interval: weekStarts.length > 20 ? 3 : 0 },
      },
      yAxis: {
        type: "category",
        data: ["一", "二", "三", "四", "五", "六", "日"],
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { fontSize: 12, color: "#71717a" },
      },
      visualMap: {
        min: 0,
        max,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 60,
        textStyle: { fontSize: 10 },
        inRange: { color: ["#eef2ff", "#c7d2fe", "#818cf8", "#4f46e5"] },
      },
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: "rgba(255,255,255,.6)", borderWidth: 1, borderRadius: 2 },
          emphasis: { itemStyle: { shadowBlur: 4, shadowColor: "rgba(0,0,0,.2)" } },
        },
      ],
    };
  }, [heat.data]);

  const radarOption = useMemo(() => {
    const items = caps.data?.items ?? [];
    return {
      radar: {
        radius: "62%",
        splitNumber: 4,
        indicator: items.map((item) => ({ name: item.name, max: 5 })),
        axisName: { color: "#71717a", fontSize: 12 },
        splitLine: { lineStyle: { color: "rgba(128,128,128,.2)" } },
        splitArea: { areaStyle: { color: ["transparent"] } },
        axisLine: { lineStyle: { color: "rgba(128,128,128,.2)" } },
      },
      tooltip: {},
      series: [
        {
          type: "radar",
          data: [
            {
              value: items.map((item) => item.avg_strength),
              name: "平均证据强度",
              areaStyle: { color: "rgba(79,70,229,.16)" },
              lineStyle: { color: "#4f46e5", width: 2 },
              itemStyle: { color: "#4f46e5" },
            },
          ],
        },
      ],
    };
  }, [caps.data]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">数据分析</h2>
          <p className="mt-1 text-base text-muted-foreground">
            能力证据按月统计；数据不足的模块显示空态
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-md border border-border bg-card p-0.5">
          {RANGES.map((item) => (
            <Button
              key={item.key}
              variant={range === item.key ? "secondary" : "ghost"}
              size="sm"
              className={cn("h-7 px-2.5 text-xs", range === item.key && "font-medium")}
              onClick={() => setRange(item.key)}
            >
              {item.label}
            </Button>
          ))}
        </div>
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>成长轨迹</CardTitle>
            <CardDescription>
              按月新增的能力证据（原文 + 推断）与能力覆盖；不用事项数代替成长
            </CardDescription>
          </div>
          <Badge variant="muted">capability_evidence</Badge>
        </CardHeader>
        <CardContent className="pt-1">
          {growth.loading ? (
            <PageSkeleton rows={0} />
          ) : growth.error ? (
            <ErrorState message={growth.error} onRetry={growth.reload} />
          ) : growth.data && growth.data.months.length > 0 ? (
            <EChart option={growthOption(growth.data)} height={300} />
          ) : (
            <EmptyState title="还没有能力证据" description="先在能力画像页确认证据，再回来看趋势。" />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>事项节奏</CardTitle>
            <CardDescription>每周事项数与 4 周移动平均，只反映交付节奏，不当作成长指标</CardDescription>
          </div>
          <Badge variant="muted">work_item</Badge>
        </CardHeader>
        <CardContent className="pt-1">
          {trend.loading ? (
            <PageSkeleton rows={0} />
          ) : trend.error ? (
            <ErrorState message={trend.error} onRetry={trend.reload} />
          ) : (
            <EChart option={trendOption} height={240} />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>工作构成</CardTitle>
              <CardDescription>按事项类型</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-1">
            {mix.loading ? (
              <PageSkeleton rows={0} />
            ) : mix.data && mix.data.by_type.length > 0 ? (
              <EChart option={mixOption} height={280} />
            ) : (
              <EmptyState title="还没有类型数据" description="事项入库后会自动带上 item_type。" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>活跃热力图</CardTitle>
              <CardDescription>颜色越深记录越多；周报精度为「周」，落在周一</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="pt-1">
            {heat.loading ? (
              <PageSkeleton rows={0} />
            ) : heat.data && heat.data.cells.some((cell) => cell.count > 0) ? (
              <EChart option={heatOption} height={280} />
            ) : (
              <EmptyState title="还没有足够的时间分布" description="至少需要几周的事项记录才能看出节奏。" />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>能力覆盖</CardTitle>
              <CardDescription>
                半径是平均证据强度（1–5）；{caps.data?.summary.covered ?? 0}/{caps.data?.summary.capability_count ?? 0} 项有证据
              </CardDescription>
            </div>
            <Badge variant="info">capability</Badge>
          </CardHeader>
          <CardContent className="pt-1">
            {caps.loading ? (
              <PageSkeleton rows={0} />
            ) : caps.data && caps.data.items.some((item) => item.evidence_count > 0) ? (
              <EChart option={radarOption} height={280} />
            ) : (
              <EmptyState
                title="还没有能力证据"
                description="在能力画像页运行标注并确认建议后，这里会显示覆盖与强度。"
                icon={<Waypoints className="h-6 w-6" />}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>阶段对比</CardTitle>
              <CardDescription>不同阶段的能力变化</CardDescription>
            </div>
            <Badge variant="warning">数据未建立</Badge>
          </CardHeader>
          <CardContent>
            <EmptyState
              title="还没有阶段快照"
              description="growth_stage 与 growth_snapshot 尚无数据；阶段快照生成后才能做对比。"
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
