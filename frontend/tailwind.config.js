/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        deplot: {
          bg: "#06080f",
          surface: "#0c1019",
          muted: "#71717a",
          accent: "#6366f1",
          violet: "#a855f7",
          cyan: "#22d3ee",
          success: "#34d399",
          warning: "#fbbf24",
          critical: "#f87171",
        },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px -10px rgba(99, 102, 241, 0.4)",
        "glow-sm": "0 0 20px -5px rgba(99, 102, 241, 0.3)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        float: "float 6s ease-in-out infinite",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
      },
    },
  },
  plugins: [],
};
