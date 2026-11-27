import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import type { EChartsOption } from "echarts";
import { BarChart, HeatmapChart, LineChart, RadarChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { cn } from "@/lib/utils";

// 只注册用到的图表与组件：完整包 1.3MB，按需引入后约 400KB
echarts.use([LineChart, BarChart, HeatmapChart, RadarChart, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CanvasRenderer]);

type Props = {
  // 允许对象字面量直接传入：ECharts 的类型要求字面量 as const，实践中过于繁琐
  option: EChartsOption | Record<string, unknown>;
  height?: number;
  className?: string;
  empty?: React.ReactNode;
};

/** ECharts 的最小封装：跟随容器尺寸、切换亮/暗主题、卸载时销毁。 */
export function EChart({ option, height = 280, className, empty }: Props) {
  const node = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!node.current) return;
    chart.current = echarts.init(node.current, document.documentElement.classList.contains("dark") ? "dark" : undefined, {
      renderer: "canvas",
    });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(node.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    // 暗色主题自带背景色，会和卡片底色分层；统一交给页面控制背景
    chart.current?.setOption({ backgroundColor: "transparent", ...option }, true);
  }, [option]);

  if (empty) return <>{empty}</>;

  return <div ref={node} className={cn("w-full", className)} style={{ height }} role="img" />;
}
