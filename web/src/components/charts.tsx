import { useEffect, useMemo, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { CalibrationPoint, EquityPoint, Probs } from '../data/types'
import { pct } from '../lib/format'

const AXIS = {
  axisLine: { lineStyle: { color: '#22304A' } },
  axisTick: { show: false },
  axisLabel: { color: '#94A3B8', fontSize: 10 },
  splitLine: { lineStyle: { color: '#172238' } },
}

const TOOLTIP = {
  backgroundColor: '#111A2C',
  borderColor: '#22304A',
  textStyle: { color: '#E2E8F0', fontSize: 12 },
}

export function EChart({ option, height = 260 }: { option: EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(ref.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [option])
  return <div ref={ref} style={{ height }} className="w-full" />
}

export function CompareHADChart({
  rows,
}: {
  rows: Array<{ label: string; probs: Probs | null }>
}) {
  const option = useMemo<EChartsOption>(() => {
    const valid = rows.filter((r) => r.probs)
    return {
      backgroundColor: 'transparent',
      tooltip: {
        ...TOOLTIP,
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (v) => pct(Number(v)),
      },
      legend: {
        top: 0,
        textStyle: { color: '#94A3B8', fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      grid: { left: 64, right: 20, top: 36, bottom: 16 },
      xAxis: {
        type: 'value',
        max: 1,
        ...AXIS,
        axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
      },
      yAxis: { type: 'category', data: valid.map((r) => r.label), ...AXIS, splitLine: { show: false } },
      series: [
        {
          name: '主胜',
          type: 'bar',
          data: valid.map((r) => r.probs?.home ?? 0),
          itemStyle: { color: '#22C55E', borderRadius: [0, 4, 4, 0] },
          barMaxWidth: 14,
        },
        {
          name: '平',
          type: 'bar',
          data: valid.map((r) => r.probs?.draw ?? 0),
          itemStyle: { color: '#64748B', borderRadius: [0, 4, 4, 0] },
          barMaxWidth: 14,
        },
        {
          name: '客胜',
          type: 'bar',
          data: valid.map((r) => r.probs?.away ?? 0),
          itemStyle: { color: '#0EA5E9', borderRadius: [0, 4, 4, 0] },
          barMaxWidth: 14,
        },
      ],
    }
  }, [rows])
  return <EChart option={option} height={Math.max(180, rows.length * 44)} />
}

export function TTGChart({ probs }: { probs: Record<string, number | null> }) {
  const option = useMemo<EChartsOption>(() => {
    const keys = ['0', '1', '2', '3', '4', '5', '6', '7+'].filter((k) => k in probs)
    return {
      tooltip: {
        ...TOOLTIP,
        trigger: 'axis',
        valueFormatter: (v) => pct(Number(v)),
      },
      grid: { left: 40, right: 16, top: 20, bottom: 28 },
      xAxis: { type: 'category', data: keys, ...AXIS, splitLine: { show: false } },
      yAxis: {
        type: 'value',
        ...AXIS,
        axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
      },
      series: [{
        type: 'bar',
        data: keys.map((k) => probs[k] ?? 0),
        itemStyle: { color: '#38BDF8', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 28,
      }],
    }
  }, [probs])
  return <EChart option={option} height={200} />
}

export function CalibrationChart({ points }: { points: CalibrationPoint[] }) {
  const option = useMemo<EChartsOption>(() => ({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      valueFormatter: (v) => pct(Number(v)),
    },
    legend: {
      top: 0,
      textStyle: { color: '#94A3B8', fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    grid: { left: 46, right: 20, top: 34, bottom: 26 },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '预测概率',
      nameTextStyle: { color: '#94A3B8', fontSize: 10 },
      ...AXIS,
      axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '实际命中',
      nameTextStyle: { color: '#94A3B8', fontSize: 10 },
      ...AXIS,
      axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
    },
    series: [
      {
        name: '实际',
        type: 'line',
        data: points.map((p) => [p.pred_mean, p.emp_freq]),
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: '#22C55E', width: 2 },
        itemStyle: { color: '#22C55E' },
        areaStyle: { color: 'rgba(34,197,94,.08)' },
      },
      {
        name: '完美校准',
        type: 'line',
        data: [[0, 0], [1, 1]],
        symbol: 'none',
        lineStyle: { color: '#475569', type: 'dashed', width: 1 },
      },
    ],
  }), [points])
  return <EChart option={option} height={260} />
}

export function EquityChart({ points }: { points: EquityPoint[] }) {
  const option = useMemo<EChartsOption>(() => ({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      valueFormatter: (v) => Number(v).toFixed(1),
    },
    grid: { left: 52, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.date),
      ...AXIS,
      splitLine: { show: false },
      axisLabel: { ...AXIS.axisLabel, showMaxLabel: true },
    },
    yAxis: { type: 'value', ...AXIS },
    series: [{
      name: '累计盈亏',
      type: 'line',
      data: points.map((p) => p.equity),
      symbol: 'none',
      lineStyle: { color: '#F59E0B', width: 2 },
      areaStyle: { color: 'rgba(245,158,11,.10)' },
    }],
  }), [points])
  return <EChart option={option} height={240} />
}

export function DailyLineChart({
  data,
  label = '命中率',
}: {
  data: Array<{ date: string; value: number | null }>
  label?: string
}) {
  const option = useMemo<EChartsOption>(() => ({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      valueFormatter: (v) => pct(Number(v)),
    },
    grid: { left: 46, right: 20, top: 22, bottom: 30 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date.slice(5)),
      ...AXIS,
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      ...AXIS,
      axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${Math.round(v * 100)}%` },
    },
    series: [{
      name: label,
      type: 'line',
      data: data.map((d) => d.value),
      connectNulls: true,
      symbolSize: 6,
      lineStyle: { color: '#22C55E', width: 2 },
      itemStyle: { color: '#22C55E' },
      areaStyle: { color: 'rgba(34,197,94,.08)' },
    }],
  }), [data, label])
  return <EChart option={option} height={240} />
}

export function ValueCumulativeChart({
  data,
}: {
  data: Array<{ date: string; value: number }>
}) {
  const option = useMemo<EChartsOption>(() => ({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      valueFormatter: (v) => Number(v).toFixed(2),
    },
    grid: { left: 52, right: 20, top: 22, bottom: 30 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date.slice(5)),
      ...AXIS,
      splitLine: { show: false },
    },
    yAxis: { type: 'value', ...AXIS },
    series: [{
      name: '累计单位注盈亏',
      type: 'line',
      data: data.map((d) => d.value),
      symbolSize: 5,
      lineStyle: { color: '#F59E0B', width: 2 },
      itemStyle: { color: '#F59E0B' },
      areaStyle: { color: 'rgba(245,158,11,.08)' },
    }],
  }), [data])
  return <EChart option={option} height={240} />
}
