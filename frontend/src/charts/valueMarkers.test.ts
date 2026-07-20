import { describe, expect, it } from 'vitest'

import { plotValueMarkers } from './valueMarkers'

const points = [
  { date: '2025-01-01', current: 1000, invested: 1000 },
  { date: '2025-01-02', current: 1500, invested: 1400 },
  { date: '2025-01-03', current: 900, invested: 800 },
]

describe('plotValueMarkers', () => {
  it('places a trade on the first available valuation date', () => {
    expect(plotValueMarkers(points, [{ date: '2024-12-31', type: 'buy', amount: 1000 }])).toEqual([
      {
        date: '2024-12-31',
        type: 'buy',
        amount: 1000,
        value: ['2025-01-01', 1000],
        count: 1,
      },
    ])
  })

  it('combines same-day trades of the same type', () => {
    const markers = plotValueMarkers(points, [
      { date: '2025-01-02', type: 'buy', amount: 200 },
      { date: '2025-01-02', type: 'buy', amount: 300 },
      { date: '2025-01-02', type: 'sell', amount: 100 },
    ])

    expect(markers).toEqual([
      {
        date: '2025-01-02',
        type: 'buy',
        amount: 500,
        value: ['2025-01-02', 1500],
        count: 2,
      },
      {
        date: '2025-01-02',
        type: 'sell',
        amount: 100,
        value: ['2025-01-02', 1500],
        count: 1,
      },
    ])
  })
})
