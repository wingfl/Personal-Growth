import { ShieldCheck, Terminal } from "lucide-react";
import { useApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/states";

type Health = {
  ok: boolean;
  db: string;
  generated_at: string;
  counts: Record<string, number>;
};

const LABELS: Record<string, string> = {
  work_item: "工作事项",
  project: "项目",
  business_system: "业务系统",
  function_module: "功能模块",
  source_document: "资料",
  source_fragment: "原文片段",
  change_proposal: "AI 建议",
  capability_evidence: "能力证据",
  growth_snapshot: "成长快照",
};

export function Settings() {
  const { data, error, loading, reload } = useApi<Health>("/api/health");

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">设置</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          界面只读：所有改动与运维动作都在命令行完成，界面只负责展示与解释
        </p>
      </div>

      {loading ? (
        <PageSkeleton rows={2} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        data && (
          <>
            <Card>
              <CardHeader>
                <div>
                  <CardTitle className="text-base">数据源</CardTitle>
                  <CardDescription>本地 SQLite，单用户，不联网</CardDescription>
                </div>
                <Badge variant="success">
                  <ShieldCheck className="mr-0.5 h-3 w-3" /> 正常
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs text-muted-foreground">数据库路径</div>
                  <code className="mt-0.5 block select-all break-all rounded-md bg-muted px-3 py-2 text-xs">
                    {data.db}
                  </code>
                </div>
                <div>
                  <div className="mb-1.5 text-xs text-muted-foreground">记录数</div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {Object.entries(data.counts).map(([key, value]) => (
                      <div key={key} className="flex items-baseline justify-between rounded-md border border-border px-3 py-2">
                        <span className="text-xs text-muted-foreground">{LABELS[key] ?? key}</span>
                        <span className="num text-sm font-medium">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  读取时间：{data.generated_at.slice(0, 16).replace("T", " ")}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle className="text-base">常用命令</CardTitle>
                  <CardDescription>写操作、备份、体检都在这里</CardDescription>
                </div>
                <Terminal className="h-4 w-4 text-muted-foreground" aria-hidden />
              </CardHeader>
              <CardContent className="grid gap-3 text-xs sm:grid-cols-2">
                <Command text="python -m app.cli overview" note="终端版总览" />
                <Command text="python -m app.cli backup" note="备份数据库" />
                <Command text="python -m app.cli ai proposals" note="待审建议" />
                <Command text="python tools/check_all.py" note="质量闸门 9 步（含密钥扫描）" />
                <Command text="python -m app.web --port 8765" note="启动本界面" />
                <Command text="cd web && npm run build" note="前端有改动时重新构建" />
              </CardContent>
            </Card>
          </>
        )
      )}
    </div>
  );
}

function Command({ text, note }: { text: string; note: string }) {
  return (
    <div>
      <code className="block select-all rounded-md bg-muted px-3 py-2 text-2xs">{text}</code>
      <div className="mt-1 text-2xs text-muted-foreground">{note}</div>
    </div>
  );
}
