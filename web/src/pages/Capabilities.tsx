import { Link } from "react-router-dom";
import { ArrowUpRight, BadgeCheck, Quote } from "lucide-react";
import { useApi, type CapabilitiesPayload } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EChart } from "@/components/charts/EChart";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/states";
import { day } from "@/lib/utils";

function StrengthDots({ value }: { value: number | null }) {
  if (!value) return <span className="text-sm text-muted-foreground">暂无证据</span>;
  return (
    <span className="flex items-center gap-1" aria-label={`平均强度 ${value.toFixed(1)} / 5`}>
      {[1, 2, 3, 4, 5].map((step) => (
        <span
          key={step}
          className={
            "h-2 w-5 rounded-full " +
            (value >= step - 0.25 ? "bg-primary" : "bg-muted")
          }
        />
      ))}
      <span className="num ml-1 text-sm text-muted-foreground">{value.toFixed(1)}</span>
    </span>
  );
}

type Dim = { name: string; avg_strength: number | null };

function compareOption(items: Dim[], demand: { items: { name: string; share: number }[] }) {
  const share = new Map(demand.items.map((item) => [item.name, item.share]));
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { name: string; value: number[] }) =>
        p.name === "我的能力"
          ? `${p.name}：强度 ${(p.value[0] / 20).toFixed(1)} / 5`
          : `${p.name}：${Math.round(p.value[0])}% 的岗位要求`,
    },
    legend: {
      bottom: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: "#71717a", fontSize: 13 },
    },
    radar: {
      radius: "66%",
      indicator: items.map((item) => ({ name: item.name, max: 100 })),
      axisName: { color: "#71717a", fontSize: 13 },
      splitLine: { lineStyle: { color: "rgba(128,128,128,.22)" } },
      splitArea: { areaStyle: { color: ["rgba(128,128,128,.03)", "rgba(128,128,128,.07)"] } },
      axisLine: { lineStyle: { color: "rgba(128,128,128,.25)" } },
    },
    series: [
      {
        type: "radar",
        symbolSize: 6,
        data: [
          {
            name: "下一档岗位要求",
            value: items.map((item) => share.get(item.name) ?? 0),
            itemStyle: { color: "#d97706" },
            areaStyle: { color: "rgba(217,119,6,.12)" },
            lineStyle: { color: "#d97706", width: 2, type: "dashed" },
          },
          {
            name: "我的能力",
            value: items.map((item) => (item.avg_strength ? item.avg_strength * 20 : null)),
            itemStyle: { color: "#4f46e5" },
            areaStyle: { color: "rgba(79,70,229,.16)" },
            lineStyle: { color: "#4f46e5", width: 2 },
          },
        ],
      },
    ],
  };
}

export function Capabilities() {
  const { data, error, loading, reload } = useApi<CapabilitiesPayload>("/api/capabilities");

  if (loading) return <PageSkeleton rows={3} />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { summary, categories, demand } = data;
  const items = categories.flatMap((group) => group.capabilities);
  const hasEvidence = summary.evidence_total > 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">能力画像</h2>
          <p className="mt-2 text-base text-muted-foreground">
            每条证据都能回到原始事项；没有证据的能力留空，不给分
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/insights">
            看趋势 <ArrowUpRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>

      {!hasEvidence ? (
        <Card className="p-6">
          <EmptyState
            title="还没有能力证据"
            description="先把已确认的工作事项标注到能力词典：python -m app.cli capability map，然后在复盘页确认建议。"
            icon={<BadgeCheck className="h-6 w-6" />}
          />
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>我和下一档位的差距</CardTitle>
                <CardDescription>
                  实线是我的证据强度（1–5 折算成百分比），虚线是薪资 P75 以上岗位（{demand.postings} 条样本）
                  要求该项能力的占比；两项都是 0–100，看形状差在哪一维
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {demand.items.length ? (
                <EChart option={compareOption(items, demand)} height={380} />
              ) : (
                <EmptyState title="还没有足够的岗位样本" description="先跑一次采集并入库，这里会显示下一档位的能力要求。" icon={<BadgeCheck className="h-6 w-6" />} />
              )}
            </CardContent>
          </Card>

          <div className="space-y-6">
            {categories.map((group) => (
              <section key={group.name} className="space-y-3">
                <h3 className="text-lg font-semibold">{group.name}</h3>
                <div className="grid gap-4 lg:grid-cols-2">
                  {group.capabilities.map((item) => (
                    <Card key={item.id} className="p-6">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-lg font-semibold">{item.name}</div>
                          <div className="mt-1 text-sm text-muted-foreground">{item.definition}</div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Badge variant={item.evidence_count ? "info" : "muted"}>
                            {item.evidence_count ? `${item.evidence_count} 条` : "待积累"}
                          </Badge>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center justify-between gap-3">
                        <StrengthDots value={item.avg_strength} />
                        <span className="num text-sm text-muted-foreground">
                          {item.last_evidence_at ? `最近 ${day(item.last_evidence_at)}` : ""}
                        </span>
                      </div>
                      {item.recent[0] && (
                        <div className="mt-4 rounded-md bg-muted/60 p-3">
                          <div className="flex gap-2 text-sm leading-6">
                            <Quote className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                            <span>{item.recent[0].statement}</span>
                          </div>
                          <div className="mt-1 flex items-center gap-2 pl-5 text-xs text-muted-foreground">
                            <span className="truncate">原文：{item.recent[0].strength_basis}</span>
                          </div>
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
