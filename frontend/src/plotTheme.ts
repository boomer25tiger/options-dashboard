// Read live CSS variables so Plotly charts match the active theme (dark/light).
// Reading at render time means a theme toggle re-themes the charts on re-render.

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function plotColors() {
  return {
    text: cssVar('--text'),
    muted: cssVar('--text-muted'),
    grid: cssVar('--border'),
    border: cssVar('--border-strong'),
    accent: cssVar('--accent'),
    pos: cssVar('--pos'),
    neg: cssVar('--neg'),
    surface: cssVar('--surface'),
    sans: cssVar('--sans') || 'sans-serif',
  }
}

// A perceptual scale from muted blue through the gold accent to red, used for the
// IV surface so magnitude reads at a glance while staying in the app's register.
export function ivColorscale(): [number, string][] {
  return [
    [0, '#3d5a80'],
    [0.5, cssVar('--accent') || '#c9a24e'],
    [1, cssVar('--neg') || '#d0696f'],
  ]
}

export function baseLayout() {
  const c = plotColors()
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: c.text, family: c.sans, size: 12 },
    margin: { l: 58, r: 18, t: 16, b: 46 },
    hovermode: 'closest' as const,
    hoverlabel: { bgcolor: c.surface, bordercolor: c.border, font: { color: c.text } },
    showlegend: false,
    xaxis: {
      gridcolor: c.grid, zerolinecolor: c.grid, linecolor: c.grid,
      tickfont: { color: c.muted }, titlefont: { color: c.muted },
    },
    yaxis: {
      gridcolor: c.grid, zerolinecolor: c.grid, linecolor: c.grid,
      tickfont: { color: c.muted }, titlefont: { color: c.muted },
    },
  }
}

export const plotConfig = { displayModeBar: false, responsive: true }
