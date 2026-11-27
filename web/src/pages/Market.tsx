import { useMemo } from "react";
import { BriefcaseBusiness, MapPin, TrendingUp } from "lucide-react";
import { useApi } from "@/lib/api";
import type { MarketGroup, MarketPayload } from "@/lib/api";
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
  value == null ? "—" : `${(value / 1000).toFixed(1)}k`;

function Band({ group, current }: { group: MarketGroup; current: number | null }) {
  const { salary_p25: p25, salary_p50: p50, salary_p75: p75 } = group;
  const hasBand = p25 != null && p50 != null && p75 != null;
  const max = Math.max(p75 ?? 0, current ?? 0) * 1.15 || 1;
  const left = (value: number) => `${Math.min(100, Math.max(0, (value / max) * 100))}%`;
  const mid = current == null ? null : (current - p50!) / p50!;

  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted-foreground">
          P25 {money(p25)} · 中位 <span className="font-medium text-foreground">{money(p50)}</span> · P75 {money(p75)}
        </span>
        {mid != null && (
          <span className={cn("tabular-nums", mid >= 0 ? "text-emerald-600" : "text-amber-600")}>
            {mid >= 0 ? "高于中位" : "低于中位"} {Math.abs(Math.round(mid * 100))}%
          </span>
        )}
      </div>
      {hasBand && (
        <div className="relative mt-2 h-3 rounded-full bg-secondary">
          <div
            className="absolute inset-y-0 rounded-full bg-primary/25"
            style={{ left: left(p25), right: `calc(100% - ${left(p75)})` }}
          />
          <div
            className="absolute top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded bg-primary"
            style={{ left: left(p50) }}
          />
          {current != null && (
            <div
              className="absolute -top-1 h-5 w-2 -translate-x-1/2 rounded-sm border-2 border-background bg-amber-500 shadow"
              style={{ left: left(current) }}
              title={`月薪 ${current}`}
            />
          )}
        </div>
      )}
      <div className="mt-1 flex justify-between text-xs text-muted-foreground">
        <span>P25</span>
        <span>{current != null ? "琥珀色标记 = 当前月薪" : "profile set --current-salary 补充后可与样本对照"}</span>
        <span>P75</span>
      </div>
    </div>
  );
}

function GroupCard({ group, current }: { group: MarketGroup; current: number | null }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-lg">{group.keyword || FAMILY[group.role_family] || group.role_family}</CardTitle>
            <CardDescription>
              {FAMILY[group.role_family] ?? group.role_family} · {group.postings} 条样本
            </CardDescription>
          </div>
          <Badge variant="muted">{group.salary_samples} 条有薪资</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <Band group={group} current={current} />
        {!!group.top_tags?.length && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {group.top_tags.slice(0, 10).map((tag) => (
              <span key={tag.tag} className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                {tag.tag} <span className="text-muted-foreground">{tag.count}</span>
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function Market() {
  const { data, error, loading, reload } = useApi<MarketPayload>("/api/market");
  const groups = useMemo(() => data?.groups ?? [], [data]);
  const median = useMemo(() => {
    const values = groups.map((g) => g.salary_p50).filter((v): v is number => v != null);
    if (!values.length) return null;
    values.sort((a, b) => a - b);
    return values[Math.floor(values.length / 2)];
  }, [groups]);

  if (loading) return <PageSkeleton />;
  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">市场定位</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          用公开招聘样本看同类岗位的要求与薪资带，再对照已有证据；不计算综合评分。
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <BriefcaseBusiness className="h-4 w-4" /> 岗位样本
            </CardDescription>
            <CardTitle className="text-3xl">{data?.total_postings ?? 0}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            来自 51job 列表页；不含 JD 正文与候选人信息
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <MapPin className="h-4 w-4" /> 城市
            </CardDescription>
            <CardTitle className="text-3xl">{data?.cities?.join(" / ") || "—"}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {groups.length} 个方向 · 样本中位月薪 {money(median)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4" /> 我的月薪
            </CardDescription>
            <CardTitle className="text-3xl">{money(data?.current_salary)}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {data?.current_salary
              ? `目标岗位：${data?.role || "—"}`
              : "用 python -m app.cli profile set --current-salary 补充"}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map((group) => (
          <GroupCard key={`${group.role_family}:${group.keyword}`} group={group} current={data?.current_salary ?? null} />
        ))}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">怎么看这些数</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>{data?.caveat}</p>
          <p>
            薪资带是「区间中值」的分位数，不是 offer 价；高频标签只能说明招聘方怎么写要求，不等于岗位真实门槛。
            需要补什么，回到能力画像查看缺失的证据类型。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
