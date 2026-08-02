export const themeTokens = {
  spacing: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
  },
  radius: {
    sm: '0.5rem',
    md: '0.75rem',
    lg: '1rem',
  },
  typography: {
    sans: "Inter, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    mono: "'SFMono-Regular', ui-monospace, monospace",
  },
  color: {
    canvas: '#020617',
    surface: '#0f172a',
    surfaceAlt: '#111827',
    border: '#1f2937',
    text: '#f8fafc',
    muted: '#94a3b8',
    accent: '#22d3ee',
  },
  elevation: {
    panel: '0 18px 50px rgba(2, 6, 23, 0.35)',
    overlay: '0 28px 80px rgba(2, 6, 23, 0.55)',
  },
  animation: {
    fast: '150ms',
    normal: '220ms',
  },
} as const
