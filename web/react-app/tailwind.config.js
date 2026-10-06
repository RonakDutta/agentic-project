/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', '"Liberation Mono"', 'monospace'],
      },
      colors: {
        canvas: '#0b0e14',
        panel: '#10141c',
        panel2: '#0c1017',
        line: '#1d2431',
        linesoft: '#171d28',
        ink: '#e6eaf1',
        muted: '#8c96a8',
        accent: '#4f8cff',
        primary: '#2f6fe4',
      },
    },
  },
  plugins: [],
}
