/**
 * Locator design tokens. Components use ONLY these semantic names
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
        // Locator brand blue (#1360EF, sampled from the logo).
        primary: {
          DEFAULT: "#1360EF",
          50: "#EEF4FF",
          100: "#DCE7FE",
          200: "#B9CFFD",
          300: "#8AB0FA",
          400: "#4F87F5",
          500: "#2A6DF2",
          600: "#1360EF",
          700: "#0E4CC4",
          800: "#0F3F9C",
          900: "#11357B",
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
        glow: "0 8px 24px rgba(19, 96, 239, 0.35)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        "pin-bounce": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        },
        "pin-pulse": {
          "0%": { transform: "scale(0.6)", opacity: "0.7" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s linear infinite",
        "fade-in": "fade-in 200ms ease-out",
        "pin-bounce": "pin-bounce 1.2s ease-in-out infinite",
        "pin-pulse": "pin-pulse 1.6s ease-out infinite",
      },
    },
  },
  plugins: [],
};
