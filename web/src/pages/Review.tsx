import { useState } from "react";
import { FileClock, TerminalSquare } from "lucide-react";
import { useApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/input";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/states";
import { readable } from "@/lib/labels";
import { day } from "@/lib/utils";

type DocCard = {
  id: string;
  title: string;
  period_start: string | null;
  period_end: string | null;
  fragment_count: number;
  proposal_counts: Record<string, number>;
};
type DocsPayload = { total: number; items: DocCard[] };
type Proposal = {
  id: string;
  change_type: string;
  entity: string;
  summary: string | null;
  created_at: string | null;
};
type ProposalsPayload = { total: number; items: Proposal[] };

const ENTITY_LABEL: Record<string, string> = {
  work_item: "工作事项",
  project: "项目",
  business_system: "业务系统",
  function_module: "功能模块",
  work_domain: "工作领域",
};

export function Review() {
  const [tab, setTab] = useState("pending");
  const docs = useApi<DocsPayload>("/api/documents?limit=100");
  const proposals = useApi<ProposalsPayload>("/api/proposals?status=pending");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">复盘</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            资料是原料，建议是半成品；确认之后才写进正式档案。首期只读，确认/拒绝仍在命令行。
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => { docs.reload(); proposals.reload(); }}>
          刷新
        </Button>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="pending">待处理建议 {proposals.data ? `(${proposals.data.total})` : ""}</TabsTrigger>
          <TabsTrigger value="documents">资料 {docs.data ? `(${docs.data.total})` : ""}</TabsTrigger>
          <TabsTrigger value="how">怎么确认</TabsTrigger>
        </TabsList>

        <TabsContent value="pending" className="mt-4 space-y-3">
          {proposals.loading ? (
            <PageSkeleton rows={2} />
          ) : proposals.error ? (
            <ErrorState message={proposals.error} onRetry={proposals.reload} />
          ) : proposals.data && proposals.data.items.length === 0 ? (
            <EmptyState
              title="没有待处理的建议"
              description="所有提取结果都已确认或拒绝。新导入资料并提取后，待审建议会出现在这里。"
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">实体</th>
                    <th className="px-4 py-2.5 font-medium">动作</th>
                    <th className="px-4 py-2.5 font-medium">摘要</th>
                    <th className="px-4 py-2.5 font-medium">生成时间</th>
                  </tr>
                </thead>
                <tbody>
                  {proposals.data?.items.map((proposal) => (
                    <tr key={proposal.id} className="border-t border-border hover:bg-muted/40">
                      <td className="whitespace-nowrap px-4 py-2.5">
                        {ENTITY_LABEL[proposal.entity] ?? proposal.entity}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge variant={proposal.change_type === "create" ? "info" : "muted"}>
                          {proposal.change_type === "create" ? "新建" : proposal.change_type}
                        </Badge>
                      </td>
                      <td className="max-w-[420px] truncate px-4 py-2.5 text-muted-foreground">
                        {readable(proposal.summary)}
                      </td>
                      <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                        {day(proposal.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="documents" className="mt-4">
          {docs.loading ? (
            <PageSkeleton rows={2} />
          ) : docs.error ? (
            <ErrorState message={docs.error} onRetry={docs.reload} />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">资料</th>
                    <th className="px-4 py-2.5 font-medium">期间</th>
                    <th className="px-4 py-2.5 font-medium">片段</th>
                    <th className="px-4 py-2.5 font-medium">提取状态</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.data?.items.map((doc) => {
                    const counts = doc.proposal_counts ?? {};
                    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
                    return (
                      <tr key={doc.id} className="border-t border-border hover:bg-muted/40">
                        <td className="px-4 py-2.5">{doc.title}</td>
                        <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                          {day(doc.period_start)} ~ {day(doc.period_end)}
                        </td>
                        <td className="num px-4 py-2.5 text-xs">{doc.fragment_count}</td>
                        <td className="px-4 py-2.5 text-xs">
                          {total === 0 ? (
                            <span className="text-muted-foreground">未提取</span>
                          ) : (
                            <div className="flex gap-1">
                              {Object.entries(counts).map(([status, count]) => (
                                <Badge key={status} variant={status === "pending" ? "warning" : "success"}>
                                  {status === "pending" ? "待审" : status} {count}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="how" className="mt-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle className="text-base">确认一条建议</CardTitle>
                <CardDescription>写操作留在命令行，避免在没有鉴权的界面上改档案</CardDescription>
              </div>
              <TerminalSquare className="h-4 w-4 text-muted-foreground" aria-hidden />
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Command text="python -m app.cli ai proposals" note="列出待审建议" />
              <Command text="python -m app.cli ai show <建议ID>" note="看这条建议的完整内容与来源片段" />
              <Command text="python -m app.cli ai confirm <建议ID>" note="确认写入正式档案" />
              <Command text="python -m app.cli ai confirm <建议ID> --set system_id=<系统ID>" note="缺必填字段时补齐后再确认" />
              <Command text="python -m app.cli ai reject <建议ID> --note 理由" note="拒绝并留下理由" />
              <p className="pt-2 text-xs text-muted-foreground">
                <FileClock className="mr-1 inline h-3.5 w-3.5" aria-hidden />
                批量入库可用 <code className="rounded bg-muted px-1">tools/oneoff/_extract_all.py --only-missing</code>，
                它逐篇提取并自动确认，缺的事项时间会按资料期间补齐。
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Command({ text, note }: { text: string; note: string }) {
  return (
    <div>
      <code className="block select-all rounded-md bg-muted px-3 py-2 text-xs text-foreground">{text}</code>
      <div className="mt-1 text-2xs text-muted-foreground">{note}</div>
    </div>
  );
}
