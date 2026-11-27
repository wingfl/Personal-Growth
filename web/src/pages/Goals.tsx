import { ArrowRight, Compass, Flag, Lightbulb, Target } from "lucide-react";
import { Link } from "react-router-dom";
import { useApi, type GoalCard, type Suggestion } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/utils";

type GoalsPayload = {
  generated_at: string;
  goals: GoalCard[];
  suggestions: Suggestion[];
  persisted: boolean;
  note: string;
};

const SEVERITY: Record<string, { label: string; variant: "danger" | "warning" | "muted" }> = {
  high: { label: "优先", variant: "danger" },
  medium: { label: "建议", variant: "warning" },
  low: { label: "可选", variant: "muted" },
};

const KIND_LABEL: Record<string, string> = {
  data: "数据完整性",
  insight: "结构洞察",
  growth: "能力成长",
};

const GOAL_TYPE: Record<string, string> = {
  capability: "能力提升",
  experience: "经验积累",
  output: "成果产出",
  completeness: "资料补全",
  habit: "习惯养成",
  other: "其他",
};

const GOAL_STATUS: Record<string, { label: string; variant: "success" | "info" | "muted" | "warning" }> = {
  proposed: { label: "建议中", variant: "muted" },
  active: { label: "进行中", variant: "info" },
  paused: { label: "已暂停", variant: "warning" },
  achieved: { label: "已达成", variant: "success" },
  abandoned: { label: "已放弃", variant: "muted" },
};

function deadline(goal: GoalCard) {
  if (goal.status === "achieved") return "已达成";
  if (!goal.end_date) return "长期";
  const days = goal.days_left ?? 0;
  if (days < 0) return `已超期 ${-days} 天`;
  if (days === 0) return "今天到期";
  return `还剩 ${days} 天`;
}

function GoalRow({ goal }: { goal: GoalCard }) {
  const status = GOAL_STATUS[goal.status] ?? GOAL_STATUS.active;
  const percent = Math.max(0, Math.min(100, goal.progress_percent));
  const late = goal.status !== "achieved" && (goal.days_left ?? 1) < 0;
  return (
    <Card className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{goal.name}</span>
            <Badge variant={status.variant}>{status.label}</Badge>
            <Badge variant="outline">{GOAL_TYPE[goal.goal_type] ?? goal.goal_type}</Badge>
            {goal.project_name ? <Badge variant="muted">{goal.project_name}</Badge> : null}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {goal.success_criteria || goal.measurement_note || "还没有写达成标准"}
          </p>
        </div>
        <span className={cn("text-xs", late ? "text-danger" : "text-muted-foreground")}>
          {deadline(goal)}
        </span>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar"
             aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
        </div>
        <span className="num text-xs text-muted-foreground">{percent}%</span>
      </div>
      {goal.progress_note ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{goal.progress_note}</p>
      ) : null}
    </Card>
  );
}

export function Goals() {
  const { data, error, loading, reload } = useApi<GoalsPayload>("/api/goals");

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">成长目标</h2>
        <p className="mt-2 max-w-2xl text-base text-muted-foreground">
          你为自己定的、可验收的成长目标；下面是根据真实数据算出的补全建议。
        </p>
      </section>

      {loading ? (
        <PageSkeleton rows={3} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <>
          <section className="space-y-3">
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-medium text-muted-foreground">正在跟踪</h3>
              <code className="text-2xs text-muted-foreground">
                python -m app.cli goal add "目标" --type capability --start 2026-12-01 --end 2027-03-31
              </code>
            </div>
            {data?.goals.length ? (
              data.goals.map((goal) => <GoalRow key={goal.id} goal={goal} />)
            ) : (
              <EmptyState
                title="还没有可跟踪的目标"
                description="目标由你确认后建立：命令行执行 goal add，填上周期与达成标准；系统只会给建议，不会替你定目标。"
                icon={<Target className="h-6 w-6" />}
              />
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground">系统建议</h3>
            {data?.suggestions.length === 0 ? (
              <EmptyState
                title="暂时没有可给的成长建议"
                description="这不是出错：当前数据没有明显缺口。等能力词典建成、阶段快照生成后，这里会出现更具体的「补齐某项能力」建议。"
                icon={<Compass className="h-6 w-6" />}
              />
            ) : (
              <div className="grid gap-3">
                {data?.suggestions.map((suggestion) => {
                  const severity = SEVERITY[suggestion.severity] ?? SEVERITY.low;
                  const target = suggestion.id === "capability-gap" ? "/insights" : "/archive";
                  return (
                    <Card key={suggestion.id} className="p-6">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="flex items-start gap-3">
                          <div className="mt-0.5 rounded-md bg-primary-weak p-1.5 text-primary">
                            <Lightbulb className="h-4 w-4" aria-hidden />
                          </div>
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">{suggestion.title}</span>
                              <Badge variant={severity.variant}>{severity.label}</Badge>
                              <Badge variant="outline">
                                {KIND_LABEL[suggestion.kind] ?? suggestion.kind}
                              </Badge>
                            </div>
                            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                              {suggestion.rationale}
                            </p>
                          </div>
                        </div>
                        <Button asChild variant="outline" size="sm">
                          <Link to={target}>
                            {suggestion.action} <ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        </Button>
                      </div>
                    </Card>
                  );
                })}
              </div>
            )}
          </section>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Flag className="h-4 w-4 text-muted-foreground" aria-hidden />
                <div>
                  <CardTitle className="text-base">目标与建议的区别</CardTitle>
                  <CardDescription>建议是系统算出来的；目标是你确认后才成立的</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">
              {data?.note}
              <br />
              目标存在 <code className="rounded bg-muted px-1 py-0.5 text-xs">growth_goal</code> 表，
              进度只在你确认后更新（<code className="rounded bg-muted px-1 py-0.5 text-xs">goal update --progress</code>）；
              AI 可以建议目标，但不会直接改你的正式档案。
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            生成时间：{data?.generated_at.slice(0, 16).replace("T", " ")}
          </p>
        </>
      )}
    </div>
  );
}
