/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        aicte: {
          navy: '#0f2942',
          blue: '#1e3a8a',
          lightBlue: '#3b82f6',
          saffron: '#f97316',
          saffronDark: '#c2410c',
          emerald: '#059669',
          amber: '#d97706',
          slate: '#334155',
          surface: '#f8fafc',
          card: '#ffffff',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
