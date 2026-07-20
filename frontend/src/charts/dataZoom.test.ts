import { describe, expect, it } from 'vitest'

import { buildDataZoom } from './dataZoom'
import type { ChartTokens } from './useChartTokens'

const tokens: ChartTokens = {
  text: '#ffffff',
  muted: '#999999',
  border: '#333333',
  surface: '#111111',
  verified: '#00aaaa',
  gain: '#00aa00',
  loss: '#aa0000',
  assetPalette: [],
}

describe('buildDataZoom', () => {
  it('supports wheel zoom and keeps the overview slider', () => {
    const [inside, slider] = buildDataZoom(tokens)

    expect(inside).toMatchObject({
      type: 'inside',
      filterMode: 'filter',
      zoomOnMouseWheel: true,
      moveOnMouseWheel: false,
    })
    expect(slider).toMatchObject({ type: 'slider', filterMode: 'filter' })
  })
})
