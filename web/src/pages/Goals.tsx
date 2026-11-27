import { ArrowRight, Compass, Lightbulb } from "lucide-react";
import { Link } from "react-router-dom";
import { useApi, type Suggestion } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/states";

type GoalsPayload = {
  generated_at: string;
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

export function Goals() {
  const { data, error, loading, reload } = useApi<GoalsPayload>("/api/goals");

  return (
    <div className="space-y-5">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">成长目标</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          这里不是工作目标，而是系统读完成长档案后给出的「下一步该补什么」：补哪段证据、补哪个维度、把哪些经历整理成案例。
          建议由真实数据算出，暂不持久化；等你确认后，才会成为可跟踪的目标。
        </p>
      </section>

      {loading ? (
        <PageSkeleton rows={2} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.suggestions.length === 0 ? (
        <EmptyState
          title="暂时没有可给的成长建议"
          description="这不是出错：当前数据没有明显缺口。等能力词典建成、阶段快照生成后，这里会出现更具体的「补齐某项能力」建议。"
          icon={<Compass className="h-6 w-6" />}
        />
      ) : (
        <>
          <div className="grid gap-3">
            {data.suggestions.map((suggestion) => {
              const severity = SEVERITY[suggestion.severity] ?? SEVERITY.low;
              const target =
                suggestion.id === "domain-gap"
                  ? "/archive"
                  : suggestion.id === "goal-gap" || suggestion.id === "thin-projects"
                    ? "/archive"
                    : "/insights";
              return (
                <Card key={suggestion.id} className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5 rounded-md bg-primary-weak p-1.5 text-primary">
                        <Lightbulb className="h-4 w-4" aria-hidden />
                      </div>
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{suggestion.title}</span>
                          <Badge variant={severity.variant}>{severity.label}</Badge>
                          <Badge variant="outline">{KIND_LABEL[suggestion.kind] ?? suggestion.kind}</Badge>
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

          <Card>
            <CardHeader>
              <div>
                <CardTitle className="text-base">为什么还没有真正的「目标」实体</CardTitle>
                <CardDescription>当前模型里能表达目标位置的只有 project.goal 与 work_theme</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">
              {data.note}
              如果你要的是「可量化、有周期、能跟踪进度」的成长目标（例如：三个月内补齐数据建模能力的三条证据），
              建议新增 <code className="rounded bg-muted px-1 py-0.5 text-xs">growth_goal</code> 实体，
              字段包含目标描述、依据证据、目标周期、验收标准、状态；这属于模型变更，需要单独确认后再做。
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">生成时间：{data.generated_at.slice(0, 16).replace("T", " ")}</p>
        </>
      )}
    </div>
  );
}
