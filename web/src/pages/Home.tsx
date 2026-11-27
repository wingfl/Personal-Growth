import { Link } from "react-router-dom";
import { ArrowRight, FileText, FolderKanban, Sparkles } from "lucide-react";
import { useApi, type GrowthPayload, type Summary } from "@/lib/api";
import { StatCard } from "@/components/ui/stat-card";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageSkeleton, ErrorState, EmptyState } from "@/components/ui/states";
import { EChart } from "@/components/charts/EChart";
import { growthOption } from "@/lib/charts";
import { day, relativeDays } from "@/lib/utils";

export function Home() {
  const { data, error, loading, reload } = useApi<Summary>("/api/summary");
  const growth = useApi<GrowthPayload>("/api/growth?months=12");

  if (loading) return <PageSkeleton />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const { counts, todos } = data;
  const g = growth.data;
  const conclusion = g
    ? `近 12 个月新增 ${g.totals.evidence} 条证据，覆盖 ${g.totals.capabilities} 项能力（原文 ${g.totals.fact} · 推断 ${g.totals.inferred}）`
    : "按月统计能力证据，不使用事项数代替成长";

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">成长概览</h2>
          <p className="mt-2 text-base text-muted-foreground">
            {counts.documents} 篇资料 · {counts.fragments} 个片段 · {counts.items} 条事项
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/insights">
            看长期趋势 <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </Button>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="累计事项" value={counts.items} />
        <StatCard label="进行中项目" value={counts.active_projects} hint={`共 ${counts.projects} 个项目`} />
        <StatCard label="覆盖资料" value={counts.documents} hint={`${counts.fragments} 个原文片段`} />
        <StatCard
          label="待处理建议"
          value={todos.pending_proposals}
          hint={todos.pending_proposals > 0 ? "去复盘页确认" : undefined}
          delta={null}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>成长轨迹</CardTitle>
              <CardDescription>{conclusion}</CardDescription>
            </div>
            <Badge variant="muted">月</Badge>
          </CardHeader>
          <CardContent className="pt-2">
            {growth.loading ? (
              <PageSkeleton rows={0} />
            ) : growth.data && growth.data.months.length > 0 ? (
              <EChart option={growthOption(growth.data)} height={260} />
            ) : (
              <EmptyState title="还没有能力证据" description="能力画像里确认证据后，这里按月显示增长。" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>需要处理</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-1 pt-2">
            {todos.pending_proposals === 0 &&
            todos.items_missing_domain === 0 &&
            todos.projects_missing_goal === 0 ? (
              <p className="px-1 py-2 text-sm text-muted-foreground">没有需要处理的事项</p>
            ) : (
              <>
                {todos.pending_proposals > 0 && (
                  <TodoRow to="/review" label="待审建议" value={todos.pending_proposals} hint="去复盘页确认" />
                )}
                {todos.items_missing_domain > 0 && (
                  <TodoRow
                    to="/archive"
                    label="事项缺工作领域"
                    value={todos.items_missing_domain}
                    hint="补齐后领域分布可计算"
                  />
                )}
                {todos.projects_missing_goal > 0 && (
                  <TodoRow
                    to="/goals"
                    label="项目缺目标"
                    value={todos.projects_missing_goal}
                    hint="缺少目标字段"
                  />
                )}
              </>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>最近记录</CardTitle>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link to="/archive">全部</Link>
            </Button>
          </CardHeader>
          <CardContent className="pt-0">
            {data.recent_items.length === 0 ? (
              <EmptyState
                title="还没有工作事项"
                description="先导入周报或月报，再用 AI 提取；命令行：python -m app.cli import 飞书导出/周报月报-md --recursive --year 2026"
                icon={<FileText className="h-6 w-6" />}
              />
            ) : (
              <ol className="relative ml-1 border-l border-border">
                {data.recent_items.map((item) => {
                  const days = relativeDays(item.occurred_at);
                  return (
                    <li key={item.id} className="relative pl-4 pb-4 last:pb-0">
                      <span className="absolute -left-[5px] top-1.5 h-2 w-2 rounded-full bg-primary/70" />
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="num text-xs text-muted-foreground">{day(item.occurred_at)}</span>
                        {item.project_name && <Badge variant="muted">{item.project_name}</Badge>}
                        {item.is_routine && <Badge variant="outline">例行</Badge>}
                        {item.is_follow_up_needed && <Badge variant="warning">待跟进</Badge>}
                        {days !== null && days <= 30 && <Badge variant="info">{days} 天前</Badge>}
                      </div>
                      <p className="mt-1 text-sm leading-6">{item.title}</p>
                    </li>
                  );
                })}
              </ol>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>项目组合</CardTitle>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link to="/archive">全部</Link>
            </Button>
          </CardHeader>
          <CardContent className="grid gap-2 pt-0 sm:grid-cols-2">
            {data.active_projects.length === 0 ? (
              <div className="sm:col-span-2">
                <EmptyState
                  title="没有进行中的项目"
                  description="项目会从提取结果里自动建立，也可以在命令行手工创建。"
                  icon={<FolderKanban className="h-6 w-6" />}
                />
              </div>
            ) : (
              data.active_projects.map((project) => (
                <Link
                  key={project.id}
                  to={`/archive?project=${project.id}`}
                  className="rounded-md border border-border p-3 transition-colors hover:bg-muted/50"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{project.name}</span>
                    <span className="num shrink-0 text-xs text-muted-foreground">
                      {project.item_count} 条
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {project.goal || "还没写目标"}
                  </div>
                  {project.last_activity ? (
                    <div className="mt-2 flex items-center gap-1.5 text-2xs text-muted-foreground">
                      <Sparkles className="h-3 w-3" aria-hidden />
                      最近 {day(project.last_activity)}
                    </div>
                  ) : null}
                </Link>
              ))
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function TodoRow({ to, label, value, hint }: { to: string; label: string; value: number; hint: string }) {
  return (
    <Link to={to} className="flex items-start justify-between gap-3 rounded-md px-1 py-1.5 hover:bg-muted/50">
      <div>
        <div className="text-sm">{label}</div>
        <div className="text-2xs text-muted-foreground">{hint}</div>
      </div>
      <span className={`num text-lg font-semibold ${value > 0 ? "text-warning" : "text-muted-foreground"}`}>
        {value}
      </span>
    </Link>
  );
}
