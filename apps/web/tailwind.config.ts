import type { Config } from "tailwindcss";

/* Isocline: an instrument for watching work move through a graph.
   Every colour is a CSS variable (src/app/globals.css) so light and dark themes share one set of class names.
   Contour teal marks work in motion and the primary action; amber marks work waiting on a person. */
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        ink: { 950: v("ink-950"), 900: v("ink-900"), 800: v("ink-800"), 700: v("ink-700"), 600: v("ink-600"), 500: v("ink-500"),
               400: v("ink-400"), 300: v("ink-300"), 200: v("ink-200"), 100: v("ink-100") },
        canvas: v("canvas"),
        paper: v("paper"),
        line: v("line"),
        warn: v("warn"),
        accent: { 50: v("accent-50"), 100: v("accent-100"), 200: v("accent-200"), 500: v("accent-500"), 600: v("accent-600"), 700: v("accent-700") },
        state: { running: v("state-running"), completed: v("state-completed"), failed: v("state-failed"), waiting: v("state-waiting"),
                 skipped: v("state-skipped"), queued: v("state-queued") },
      },
      fontFamily: {
        sans: ['"Instrument Sans Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
      borderRadius: { md: "7px", lg: "10px", xl: "14px" },
      boxShadow: {
        node: "0 1px 0 rgb(var(--shadow) / .05), 0 4px 14px -6px rgb(var(--shadow) / .18)",
        card: "0 1px 0 rgb(var(--shadow) / .05)",
        pop: "0 16px 40px -12px rgb(var(--shadow) / .32), 0 2px 6px rgb(var(--shadow) / .08)",
      },
      keyframes: {
        pulseRing: { "0%": { boxShadow: "0 0 0 0 rgb(var(--state-running) / .45)" }, "100%": { boxShadow: "0 0 0 9px rgb(var(--state-running) / 0)" } },
        fadeIn: { "0%": { opacity: "0", transform: "translateY(3px)" }, "100%": { opacity: "1", transform: "none" } },
      },
      animation: { pulseRing: "pulseRing 1.6s ease-out infinite", fadeIn: "fadeIn .16s ease-out" },
    },
  },
  plugins: [],
} satisfies Config;
