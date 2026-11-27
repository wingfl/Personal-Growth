import { useMemo } from "react";
import { BriefcaseBusiness, Crosshair, MapPin, Sparkles, Target, TrendingUp } from "lucide-react";
import { useApi } from "@/lib/api";
import type { CapabilityGap, MarketPayload, SalaryBand, SalaryBenchmark } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/utils";

const FAMILY: Record<string, string> = {
  product: "产品",
  design: "设计",
  engineering: "研发",
  qa: "测试",
  operations: "运营",
  management: "管理",
  other: "其他",
};

const money = (value: number | null | undefined) =>
  value == null ? "—" : `¥${Math.round(value).toLocaleString()}`;

/** 我的月薪在样本分布里的位置 */
function Position({ data }: { data: MarketPayload }) {
  const { p25, p50, p75, current_salary: salary } = data;
  const max = Math.max((p75 ?? 0) * 1.25, (salary ?? 0) * 1.15, 1);
  const at = (value: number | null) =>
    value == null ? null : `${Math.min(100, Math.max(0, (value / max) * 100))}%`;

  return (
    <div className="mt-6">
      <div className="relative h-3 rounded-full bg-gradient-to-r from-secondary via-primary/25 to-primary/60">
        {salary != null && (
          <div className="absolute -top-1 h-5 w-2 -translate-x-1/2 rounded-sm border-2 border-background bg-amber-500 shadow" style={{ left: at(salary) ?? "0%" }} />
        )}
      </div>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>P25 {money(p25)}</span>
        <span>中位 {money(p50)}</span>
        <span>P75 {money(p75)}</span>
      </div>
    </div>
  );
}

function GapCard({ gap, index }: { gap: CapabilityGap; index: number }) {
  return (
    <Card className={cn(index === 0 && "border-primary/40")}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-lg">
              {index + 1}. {gap.name}
            </CardTitle>
            <CardDescription>
              P75 以上岗位提及 <span className="font-medium text-foreground">{gap.high_share}%</span>（{gap.high_count} 条）
            </CardDescription>
          </div>
          <Badge variant={gap.evidence < 5 ? "warning" : "muted"}>现有证据 {gap.evidence}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-muted-foreground">
        <p>
          {gap.evidence === 0
            ? "档案里还没有这项能力的证据，先补这一项最能缩小差距。"
            : `已有 ${gap.evidence} 条证据，但高薪岗位对这项能力的要求出现得更频繁。`}
        </p>
        {!!gap.examples.length && (
          <p className="text-xs">相关岗位：{gap.examples.join(" · ")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function BandCard({ band }: { band: SalaryBand }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{band.name}</CardTitle>
        <CardDescription>
          {band.postings} 条样本 · {money(band.salary_from)} – {band.salary_to ? money(band.salary_to) : "以上"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {band.requirements.map((req) => (
          <div key={req.code} className="flex items-center gap-3 text-sm">
            <span className="w-24 shrink-0">{req.name}</span>
            <div className="h-1.5 flex-1 rounded-full bg-secondary">
              <div className="h-1.5 rounded-full bg-primary/70" style={{ width: `${req.share}%` }} />
            </div>
            <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">{req.count} 条</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function BenchmarkRow({ item }: { item: SalaryBenchmark }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border/60 py-2 text-sm last:border-0">
      <div>
        <span className="font-medium">{item.role_name}</span>
        <span className="ml-2 text-muted-foreground">
          {[item.city, item.level, item.as_of].filter(Boolean).join(" · ")}
        </span>
      </div>
      <div className="text-muted-foreground">
        P25 {money(item.p25)} · P50 <span className="text-foreground">{money(item.p50)}</span> · P75 {money(item.p75)}
        <span className="ml-2 text-xs">{item.source}</span>
      </div>
    </div>
  );
}

export function Market() {
  const { data, error, loading, reload } = useApi<MarketPayload>("/api/market");
  const groups = useMemo(() => data?.groups ?? [], [data]);

  if (loading) return <PageSkeleton />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  const salary = data?.current_salary ?? null;
  const bandLabel = data?.band_name ?? "未定位";
  const gapToNext = data?.to_next_band;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">市场定位</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          公开岗位样本对照：现在的位置、高薪段要求什么、补哪两项最能抬档位。
        </p>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardDescription className="flex items-center gap-1.5">
                <Crosshair className="h-4 w-4" /> 我的位置
              </CardDescription>
              <div className="mt-1 flex items-baseline gap-3">
                <CardTitle className="text-3xl">{money(salary)}</CardTitle>
                <Badge variant={data?.band === "high" ? "success" : data?.band === "low" ? "warning" : "muted"}>
                  {bandLabel}
                </Badge>
              </div>
            </div>
            <div className="text-right text-sm text-muted-foreground">
              {data?.percentile != null && (
                <p>
                  高于样本中 <span className="font-medium text-foreground">{data.percentile}%</span> 的岗位
                </p>
              )}
              {gapToNext != null && gapToNext > 0 && (
                <p className="mt-1">
                  距下一档（{money(data?.next_band_at)}）还差 <span className="font-medium text-foreground">{money(gapToNext)}</span>
                </p>
              )}
              {salary == null && <p>用 profile set --current-salary 填写后定位</p>}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Position data={data!} />
          <p className="mt-3 text-xs text-muted-foreground">
            {data?.total_postings} 条样本中 {data?.salary_samples} 条有明确薪资，取区间中值；琥珀色标记为当前月薪。
          </p>
        </CardContent>
      </Card>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <Target className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold">补这两项最能抬档位</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {(data?.recommendations ?? []).map((gap, index) => (
            <GapCard key={gap.code} gap={gap} index={index} />
          ))}
          {!data?.recommendations?.length && (
            <Card>
              <CardContent className="py-8 text-sm text-muted-foreground">
                高薪段样本还不足，暂不给出建议。
              </CardContent>
            </Card>
          )}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold">分档要求频次</h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {(data?.bands ?? []).map((band) => (
            <BandCard key={band.key} band={band} />
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <BriefcaseBusiness className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold">方向样本</h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {groups.map((group) => (
            <Card key={`${group.role_family}:${group.keyword}`}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{group.keyword || FAMILY[group.role_family] || group.role_family}</CardTitle>
                    <CardDescription>
                      {group.postings} 条样本 · P25 {money(group.salary_p25)} · 中位 {money(group.salary_p50)} · P75 {money(group.salary_p75)}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {!!group.top_tags?.length && (
                  <div className="flex flex-wrap gap-1.5">
                    {group.top_tags.slice(0, 8).map((tag) => (
                      <span key={tag.tag} className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                        {tag.tag} <span className="text-muted-foreground">{tag.count}</span>
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription className="flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4" /> 行业报告口径
          </CardDescription>
          <CardTitle className="text-base">报告里的薪资分位（人工录入）</CardTitle>
        </CardHeader>
        <CardContent>
          {(data?.benchmarks ?? []).length ? (
            data!.benchmarks.map((item) => <BenchmarkRow key={`${item.role_name}:${item.city}:${item.source}`} item={item} />)
          ) : (
            <p className="text-sm text-muted-foreground">
              还没有录入报告口径。用 <code className="rounded bg-secondary px-1">python -m app.cli market benchmark add</code> 录入脉脉/智联等报告的分位，和爬虫样本互相校准。
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardDescription className="flex items-center gap-1.5">
            <MapPin className="h-4 w-4" /> 数据说明
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>{data?.caveat}</p>
          <p>要求频次按标题、标签、学历、经验折算，不等同于硬门槛；补证据的方向以能力画像里的逐年记录为准。</p>
        </CardContent>
      </Card>
    </div>
  );
}
