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
  intro?: string | null;
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

export type GrowthMonth = { month: string; label: string; fact: number; inferred: number };
export type GrowthPayload = {
  generated_at: string;
  months: GrowthMonth[];
  coverage: { month: string; label: string; covered: number }[];
  totals: { evidence: number; fact: number; inferred: number; capabilities: number };
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

export type GoalCard = {
  id: string;
  name: string;
  goal_type: string;
  description: string | null;
  status: string;
  start_date: string;
  end_date: string | null;
  date_precision: string | null;
  progress_percent: number;
  success_criteria: string | null;
  measurement_note: string | null;
  progress_note: string | null;
  project_id: string | null;
  project_name: string | null;
  domain_id: string | null;
  days_left: number | null;
};

export type Profile = {
  exists: boolean;
  display_name: string | null;
  current_title: string | null;
  company: string | null;
  industry: string | null;
  work_start_date: string | null;
  target_position: string | null;
  city: string | null;
  summary: string | null;
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

export type CapabilityEvidence = {
  id: string;
  evidence_type: string;
  strength: number | null;
  statement: string;
  strength_basis: string | null;
  occurred_at: string;
  item_title: string | null;
  project_name: string | null;
  is_fact?: number;
  fact_basis?: string | null;
};

export type Capability = {
  id: string;
  code: string;
  name: string;
  definition: string;
  typical_behavior: string | null;
  category: string;
  evidence_count: number;
  fact_count: number;
  inferred_count: number;
  avg_strength: number | null;
  fact_avg_strength: number | null;
  last_evidence_at: string | null;
  months: { month: string; count: number; avg_strength: number | null }[];
  recent: CapabilityEvidence[];
};

export type CapabilitiesPayload = {
  generated_at: string;
  framework: string;
  level_scale: string;
  summary: {
    capability_count: number;
    covered: number;
    evidence_total: number;
    fact_total: number;
    inferred_total: number;
    avg_strength: number | null;
    fact_avg_strength: number | null;
  };
  categories: { name: string; capabilities: Capability[] }[];
  items: Capability[];
};

export type MarketTag = { tag: string; count: number };

export type MarketGroup = {
  role_family: string;
  keyword: string;
  postings: number;
  salary_samples: number;
  salary_p25: number | null;
  salary_p50: number | null;
  salary_p75: number | null;
  top_tags: MarketTag[];
  companies: string[];
  vs_current_pct?: number | null;
};

export type MarketPayload = {
  generated_at: string;
  role: string;
  city: string;
  cities: string[];
  total_postings: number;
  current_salary: number | null;
  expected_salary: number | null;
  groups: MarketGroup[];
  chain: string | null;
  caveat: string;
};
