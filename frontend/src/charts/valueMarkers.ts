import type { ValuePoint } from '@/components/charts/PortfolioValueChart.vue'

export interface ValueMarker {
  date: string
  type: 'buy' | 'sell'
  amount: number | null
  securityId?: number
}

export interface PlottedValueMarker extends ValueMarker {
  value: [string, number]
  count: number
}

/** Pin trades to the first valuation point on or after their trade date. */
export function plotValueMarkers(
  points: ValuePoint[],
  markers: ValueMarker[],
): PlottedValueMarker[] {
  const grouped = new Map<string, PlottedValueMarker>()

  for (const marker of markers) {
    const point = points.find((candidate) => candidate.date >= marker.date)
    if (!point) continue

    const key = `${point.date}:${marker.type}`
    const existing = grouped.get(key)
    if (existing) {
      existing.count += 1
      if (marker.amount != null) existing.amount = (existing.amount ?? 0) + marker.amount
      continue
    }

    grouped.set(key, {
      ...marker,
      value: [point.date, point.current],
      count: 1,
    })
  }

  return [...grouped.values()]
}
