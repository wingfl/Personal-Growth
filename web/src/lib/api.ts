import { useCallback, useEffect, useState } from "react";

/** 与 app/web.py 返回结构对应的最小类型集合（只声明页面用到的字段） */
export type ItemCard = {
  id: string;
  title: string;
  occurred_at: string | null;
  date_precision: string | null;
  item_type: string | null;
  is_routine: boolean;
  is_follow_up_needed: boolean;
  project_id: string | null;
  project_name: string | null;
};

export type ProjectCard = {
  id: string;
  name: string;
  status: string | null;
  project_type?: string | null;
  my_role: string | null;
  goal: string | null;
  start_date?: string | null;
  end_date?: string | null;
  item_count: number;
  last_activity?: string | null;
  updated_at?: string | null;
};

export type Summary = {
  generated_at: string;
  counts: {
    items: number;
    projects: number;
    active_projects: number;
    documents: number;
    fragments: number;
    proposals: number;
  };
  trend: {
    weeks: { week_start: string; label: string; count: number }[];
    current_4w: number;
    previous_4w: number;
    delta_pct: number | null;
  };
  recent_items: ItemCard[];
  active_projects: ProjectCard[];
  todos: {
    pending_proposals: number;
    items_missing_domain: number;
    projects_missing_goal: number;
  };
  stages: unknown[];
};

export type Suggestion = {
  id: string;
  kind: string;
  severity: "high" | "medium" | "low";
  title: string;
  rationale: string;
  action: string;
  count: number;
};

export type MixRow = { key: string; count: number };

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* 非 JSON 错误体，保留状态码 */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export type AsyncState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

export function useApi<T>(path: string): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    get<T>(path, controller.signal)
      .then((payload) => setData(payload))
      .catch((exc: Error) => {
        if (exc.name !== "AbortError") setError(exc.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload };
}

export const api = { get };
