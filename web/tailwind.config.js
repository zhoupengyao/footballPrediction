/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0B1220',
        panel: '#111A2C',
        raised: '#172238',
        line: '#22304A',
        pitch: '#22C55E',
        amber: '#F59E0B',
        danger: '#EF4444',
        muted: '#94A3B8',
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 10px 30px rgba(0,0,0,.25)',
      },
    },
  },
  plugins: [],
}
