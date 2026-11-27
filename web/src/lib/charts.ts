import type { GrowthPayload } from "@/lib/api";

/** 成长轨迹：按月的新增证据（原文/推断）柱 + 能力覆盖累积线。 */
export function growthOption(data: GrowthPayload) {
  const months = data.months;
  return {
    grid: { left: 8, right: 8, top: 34, bottom: 4, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 12 } },
    xAxis: {
      type: "category",
      data: months.map((point) => point.label),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "rgba(128,128,128,.35)" } },
      axisLabel: { fontSize: 12, color: "#71717a" },
    },
    yAxis: [
      {
        type: "value",
        name: "新增证据",
        nameTextStyle: { fontSize: 11, color: "#71717a" },
        splitLine: { lineStyle: { color: "rgba(128,128,128,.15)" } },
        axisLabel: { fontSize: 12, color: "#71717a" },
      },
      {
        type: "value",
        name: "覆盖能力",
        max: 10,
        nameTextStyle: { fontSize: 11, color: "#71717a" },
        splitLine: { show: false },
        axisLabel: { fontSize: 12, color: "#71717a" },
      },
    ],
    series: [
      {
        name: "原文证据",
        type: "bar",
        stack: "evidence",
        data: months.map((point) => point.fact),
        barMaxWidth: 26,
        itemStyle: { color: "#4f46e5" },
      },
      {
        name: "推断证据",
        type: "bar",
        stack: "evidence",
        data: months.map((point) => point.inferred),
        barMaxWidth: 26,
        itemStyle: { color: "#a5b4fc", borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "覆盖能力",
        type: "line",
        yAxisIndex: 1,
        data: data.coverage.map((point) => point.covered),
        smooth: true,
        symbolSize: 5,
        lineStyle: { color: "#0d9488", width: 2 },
        itemStyle: { color: "#0d9488" },
      },
    ],
  };
}
