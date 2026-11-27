import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FolderKanban, Inbox, Search } from "lucide-react";
import { useApi, type ItemCard, type ProjectCard } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/input";
import { ErrorState, EmptyState, PageSkeleton } from "@/components/ui/states";
import { ITEM_TYPE_LABEL as TYPE_LABEL, DATE_PRECISION_LABEL } from "@/lib/labels";
import { day } from "@/lib/utils";

type ItemsPayload = { total: number; items: ItemCard[] };
type ProjectsPayload = { total: number; items: ProjectCard[] };
type ProjectDetail = {
  project: ProjectCard & { background?: string | null; outcome_summary?: string | null; contribution_summary?: string | null };
  items: (ItemCard & { domain_name?: string | null })[];
  item_count: number;
  by_type: { key: string; count: number }[];
};
type DocCard = {
  id: string;
  title: string;
  doc_type: string | null;
  period_start: string | null;
  period_end: string | null;
  fragment_count: number;
  proposal_counts: Record<string, number>;
};
type DocsPayload = { total: number; items: DocCard[] };


export function Archive() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState("items");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [projectId, setProjectId] = useState(params.get("project") ?? "");
  const [detail, setDetail] = useState<string | null>(params.get("project"));

  const itemPath = useMemo(() => {
    const search = new URLSearchParams({ limit: "100" });
    if (query.trim()) search.set("q", query.trim());
    if (type) search.set("type", type);
    if (projectId) search.set("project_id", projectId);
    return `/api/items?${search.toString()}`;
  }, [query, type, projectId]);

  const items = useApi<ItemsPayload>(itemPath);
  const projects = useApi<ProjectsPayload>("/api/projects");
  const documents = useApi<DocsPayload>("/api/documents?limit=100");
  const projectDetail = useApi<ProjectDetail>(detail ? `/api/projects/${detail}` : "/api/projects");

  useEffect(() => {
    if (detail) params.set("project", detail);
    else params.delete("project");
    setParams(params, { replace: true });
  }, [detail]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">成长档案</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            每条记录都能回溯到原文；这里只读，改动请用命令行
          </p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="items">事项 {items.data ? `(${items.data.total})` : ""}</TabsTrigger>
          <TabsTrigger value="projects">项目 {projects.data ? `(${projects.data.total})` : ""}</TabsTrigger>
          <TabsTrigger value="documents">资料 {documents.data ? `(${documents.data.total})` : ""}</TabsTrigger>
        </TabsList>

        <TabsContent value="items" className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索事项标题"
                className="w-64 pl-8"
              />
            </div>
            <Select value={type} onChange={(event) => setType(event.target.value)}>
              <option value="">全部类型</option>
              {Object.entries(TYPE_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
            <Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              <option value="">全部项目</option>
              {projects.data?.items.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </Select>
            {(query || type || projectId) && (
              <Button variant="ghost" size="sm" onClick={() => { setQuery(""); setType(""); setProjectId(""); }}>
                清除筛选
              </Button>
            )}
          </div>

          {items.loading ? (
            <PageSkeleton rows={2} />
          ) : items.error ? (
            <ErrorState message={items.error} onRetry={items.reload} />
          ) : items.data && items.data.items.length === 0 ? (
            <EmptyState
              title="这个筛选下没有记录"
              description="换个关键词或清除筛选；如果库里还没有事项，先导入资料并提取。"
              action={<Button variant="outline" onClick={() => { setQuery(""); setType(""); setProjectId(""); }}>清除筛选</Button>}
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">时间</th>
                    <th className="px-4 py-2.5 font-medium">事项</th>
                    <th className="px-4 py-2.5 font-medium">类型</th>
                    <th className="px-4 py-2.5 font-medium">项目</th>
                  </tr>
                </thead>
                <tbody>
                  {items.data?.items.map((item) => (
                    <tr key={item.id} className="border-t border-border hover:bg-muted/40">
                      <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                        {day(item.occurred_at)}
                        {item.date_precision && item.date_precision !== "day" && (
                          <span className="ml-1 text-2xs opacity-70">
                            {DATE_PRECISION_LABEL[item.date_precision] ?? item.date_precision}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span>{item.title}</span>
                          {item.is_routine && <Badge variant="muted">例行</Badge>}
                          {item.is_follow_up_needed && <Badge variant="warning">待跟进</Badge>}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                        {TYPE_LABEL[item.item_type ?? ""] ?? item.item_type ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 text-xs">
                        {item.project_name ? (
                          <button
                            className="text-primary hover:underline"
                            onClick={() => { setProjectId(item.project_id ?? ""); setDetail(item.project_id); setTab("projects"); }}
                          >
                            {item.project_name}
                          </button>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="projects" className="mt-4">
          {projects.loading ? (
            <PageSkeleton rows={2} />
          ) : projects.error ? (
            <ErrorState message={projects.error} onRetry={projects.reload} />
          ) : (
            <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
              <div className="grid gap-3 sm:grid-cols-2">
                {projects.data?.items.map((project) => (
                  <button
                    key={project.id}
                    onClick={() => setDetail(project.id)}
                    className={`rounded-lg border p-4 text-left transition-colors hover:bg-muted/40 ${
                      detail === project.id ? "border-primary bg-primary-weak/40" : "border-border bg-card"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{project.name}</span>
                      <Badge variant={project.status === "active" ? "success" : "muted"}>
                        {project.status ?? "未填"}
                      </Badge>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {project.goal || "还没写目标"}
                    </p>
                    <div className="mt-2 flex items-center gap-2 text-2xs text-muted-foreground">
                      <span className="num">{project.item_count} 条事项</span>
                      <span>·</span>
                      <span>最近 {day(project.last_activity)}</span>
                    </div>
                  </button>
                ))}
                {projects.data?.items.length === 0 && (
                  <div className="sm:col-span-2">
                    <EmptyState title="还没有项目" description="提取资料时，模型识别到的项目会自动建立。" icon={<FolderKanban className="h-6 w-6" />} />
                  </div>
                )}
              </div>

              <Card className="h-fit lg:sticky lg:top-20">
                {!detail ? (
                  <CardContent className="py-10 text-center text-sm text-muted-foreground">
                    选择一个项目查看详情
                  </CardContent>
                ) : projectDetail.loading ? (
                  <CardContent className="space-y-2 py-6">
                    <div className="skeleton h-5 w-2/3" />
                    <div className="skeleton h-4 w-full" />
                    <div className="skeleton h-4 w-5/6" />
                  </CardContent>
                ) : projectDetail.data ? (
                  <>
                    <CardHeader>
                      <div>
                        <CardTitle className="text-base">{projectDetail.data.project.name}</CardTitle>
                        <CardDescription>
                          {projectDetail.data.item_count} 条事项 · {projectDetail.data.project.my_role || "角色未填"}
                        </CardDescription>
                      </div>
                      <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>
                        关闭
                      </Button>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <Field label="目标" value={projectDetail.data.project.goal} />
                      <Field label="背景" value={projectDetail.data.project.background} />
                      <Field label="结果" value={projectDetail.data.project.outcome_summary} />
                      <div>
                        <div className="mb-1.5 text-xs text-muted-foreground">事项构成</div>
                        <div className="space-y-1">
                          {projectDetail.data.by_type.map((row) => (
                            <div key={row.key} className="flex items-center gap-2 text-xs">
                              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                                <div
                                  className="h-full rounded-full bg-primary/70"
                                  style={{ width: `${(row.count / Math.max(projectDetail.data!.item_count, 1)) * 100}%` }}
                                />
                              </div>
                              <span className="w-24 shrink-0 text-muted-foreground">
                                {TYPE_LABEL[row.key] ?? row.key}
                              </span>
                              <span className="num w-6 text-right">{row.count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="mb-1.5 text-xs text-muted-foreground">最近事项</div>
                        <ul className="space-y-1.5">
                          {projectDetail.data.items.slice(0, 5).map((item) => (
                            <li key={item.id} className="text-xs">
                              <span className="num mr-1.5 text-muted-foreground">{day(item.occurred_at)}</span>
                              {item.title}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </CardContent>
                  </>
                ) : (
                  <CardContent className="py-6">
                    <ErrorState message={projectDetail.error ?? "读取失败"} onRetry={projectDetail.reload} />
                  </CardContent>
                )}
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="documents" className="mt-4">
          {documents.loading ? (
            <PageSkeleton rows={2} />
          ) : documents.error ? (
            <ErrorState message={documents.error} onRetry={documents.reload} />
          ) : documents.data?.items.length === 0 ? (
            <EmptyState
              title="还没有导入资料"
              description="把飞书导出的周报/月报放进一个目录，用命令行导入。"
              icon={<Inbox className="h-6 w-6" />}
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">资料</th>
                    <th className="px-4 py-2.5 font-medium">期间</th>
                    <th className="px-4 py-2.5 font-medium">片段</th>
                    <th className="px-4 py-2.5 font-medium">建议</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.data?.items.map((doc) => (
                    <tr key={doc.id} className="border-t border-border hover:bg-muted/40">
                      <td className="px-4 py-2.5">{doc.title}</td>
                      <td className="num whitespace-nowrap px-4 py-2.5 text-xs text-muted-foreground">
                        {day(doc.period_start)} ~ {day(doc.period_end)}
                      </td>
                      <td className="num px-4 py-2.5 text-xs">{doc.fragment_count}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex gap-1">
                          {Object.entries(doc.proposal_counts ?? {}).map(([status, count]) => (
                            <Badge key={status} variant={status === "pending" ? "warning" : "muted"}>
                              {status} {count}
                            </Badge>
                          ))}
                          {Object.keys(doc.proposal_counts ?? {}).length === 0 && (
                            <span className="text-xs text-muted-foreground">未提取</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <p className="mt-0.5 text-sm leading-6">{value || <span className="text-muted-foreground">未填写</span>}</p>
    </div>
  );
}
