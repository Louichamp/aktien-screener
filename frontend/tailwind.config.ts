import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Terminal-/Research-Palette: dunkler Hintergrund, präzise Akzente
        ink: "#0a0e14",
        panel: "#111722",
        panel2: "#161d2b",
        edge: "#222c3d",
        muted: "#8b97a8",
        bull: "#22c55e",
        bear: "#ef4444",
        warn: "#f59e0b",
        accent: "#38bdf8",
      },
      fontFamily: {
        serif: ["Georgia", "Cambria", "Times New Roman", "serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
