import { Link } from "react-router-dom";
import { ArrowUpRight, BadgeCheck, Quote } from "lucide-react";
import { useApi, type Capability, type CapabilitiesPayload } from "@/lib/api";
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

function radarOption(items: Capability[], withInferred: boolean) {
  const fact = {
    value: items.map((item) => (item.fact_count ? item.fact_avg_strength : null)),
    name: "原文证据",
    itemStyle: { color: "#4f46e5" },
    areaStyle: { color: "rgba(79,70,229,.16)" },
    lineStyle: { color: "#4f46e5", width: 2 },
  };
  const all = {
    value: items.map((item) => (item.evidence_count ? item.avg_strength : null)),
    name: "含岗位链路推断",
    itemStyle: { color: "#d97706" },
    areaStyle: { color: "rgba(217,119,6,.10)" },
    lineStyle: { color: "#d97706", width: 2, type: "dashed" },
  };
  return {
    tooltip: { trigger: "item" },
    legend: withInferred
      ? { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: "#71717a", fontSize: 13 } }
      : undefined,
    radar: {
      radius: "68%",
      indicator: items.map((item) => ({ name: item.name, max: 5 })),
      axisName: { color: "#71717a", fontSize: 13 },
      splitLine: { lineStyle: { color: "rgba(128,128,128,.22)" } },
      splitArea: { areaStyle: { color: ["rgba(128,128,128,.03)", "rgba(128,128,128,.07)"] } },
      axisLine: { lineStyle: { color: "rgba(128,128,128,.25)" } },
    },
    series: [
      {
        type: "radar",
        symbolSize: 6,
        data: withInferred ? [fact, all] : [fact],
      },
    ],
  };
}

export function Capabilities() {
  const { data, error, loading, reload } = useApi<CapabilitiesPayload>("/api/capabilities");

  if (loading) return <PageSkeleton rows={3} />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { summary, categories } = data;
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

      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-6">
          <div className="text-sm font-medium text-muted-foreground">覆盖能力</div>
          <div className="num mt-1 text-3xl font-semibold">
            {summary.covered}
            <span className="ml-1 text-lg font-normal text-muted-foreground">
              / {summary.capability_count}
            </span>
          </div>
        </Card>
        <Card className="p-6">
          <div className="text-sm font-medium text-muted-foreground">已确认证据</div>
          <div className="num mt-1 text-3xl font-semibold">{summary.evidence_total}</div>
          <div className="mt-2 text-sm text-muted-foreground">
            原文 {summary.fact_total} · 链路推断 {summary.inferred_total}
          </div>
        </Card>
        <Card className="p-6">
          <div className="text-sm font-medium text-muted-foreground">平均证据强度</div>
          <div className="num mt-1 text-3xl font-semibold">
            {(summary.fact_avg_strength ?? summary.avg_strength)?.toFixed(1) ?? "—"}
            <span className="ml-1 text-lg font-normal text-muted-foreground">/ 5</span>
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            含推断后 {summary.avg_strength ? summary.avg_strength.toFixed(1) : "—"}
          </div>
        </Card>
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
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <div>
                  <CardTitle>能力维度</CardTitle>
                  <CardDescription>
                    实线是原文证据的强度；虚线是按岗位链路补出的推断（1–5），空值表示还没有证据
                  </CardDescription>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <EChart option={radarOption(items, summary.inferred_total > 0)} height={360} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>画像怎么来的</CardTitle>
                  <CardDescription>证据只从已确认记录派生</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 pt-0 text-sm text-muted-foreground">
                <p>1. 周报、月报先入库并提取成事项，人工确认。</p>
                <p>2. 标注作业把事项映射到能力词典，产出证据建议；每条都带原文引用。</p>
                <p>3. 确认后的证据才计入画像，AI 不会直接改写能力评价。</p>
                <p>4. 只写「完成评审并推进」这类里程碑时，系统会按你的岗位链路补出调研、PRD、方案、验收等隐含环节，标记为推断，和原文证据分开显示。</p>
                <p className="pt-1 text-foreground/80">{data.level_scale}</p>
              </CardContent>
            </Card>
          </div>

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
                          {item.inferred_count > 0 && (
                            <Badge variant="muted">推断 {item.inferred_count}</Badge>
                          )}
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
                            {item.recent[0].is_fact === 0 && <Badge variant="muted">推断</Badge>}
                            <span className="truncate">
                              {item.recent[0].is_fact === 0 ? "依据：" : "原文："}
                              {item.recent[0].strength_basis}
                            </span>
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
