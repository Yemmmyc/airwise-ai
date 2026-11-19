import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        airwise: {
          50: "#f0fdf9",
          100: "#ccfbef",
          200: "#99f6e0",
          300: "#5eead4",
          400: "#2dd4bf",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          800: "#115e59",
          900: "#134e4a",
          950: "#042f2e",
        },
        theme: {
          main: "var(--bg-main)",
          sidebar: "var(--bg-sidebar)",
          card: "var(--bg-card)",
          secondary: "var(--bg-surface-secondary)",
          accent: "var(--accent-primary)",
          mint: "var(--accent-secondary)",
          text: "var(--text-main)",
          muted: "var(--text-secondary)",
          border: "var(--border-subtle)",
        },
      },
    },
  },
  plugins: [],
};

export default config;
