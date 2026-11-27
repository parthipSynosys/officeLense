/**
 * EventLens design tokens. Components use ONLY these semantic names
 * (primary, background, surface, ink, line, success, warning, danger) —
 * never raw hex values — so the theme can be changed in one place.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#4F46E5",
          50: "#EEF2FF",
          100: "#E0E7FF",
          200: "#C7D2FE",
          300: "#A5B4FC",
          400: "#818CF8",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
          800: "#3730A3",
          900: "#312E81",
        },
        background: "#F8FAFC",
        surface: "#FFFFFF",
        ink: {
          DEFAULT: "#0F172A", // headings / body text (16:1 on background)
          muted: "#475569", // secondary text (7:1)
          subtle: "#64748B", // tertiary text (4.6:1, AA)
        },
        line: {
          DEFAULT: "#E2E8F0",
          strong: "#CBD5E1",
        },
        success: { DEFAULT: "#047857", soft: "#ECFDF5" },
        warning: { DEFAULT: "#B45309", soft: "#FFFBEB" },
        danger: { DEFAULT: "#B91C1C", soft: "#FEF2F2" },
        overlay: "#0B1120",
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(15, 23, 42, 0.06)",
        lifted: "0 2px 4px rgba(15, 23, 42, 0.06), 0 12px 32px rgba(15, 23, 42, 0.12)",
        glow: "0 8px 24px rgba(79, 70, 229, 0.35)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "fade-in": "fade-in 200ms ease-out",
      },
    },
  },
  plugins: [],
};
