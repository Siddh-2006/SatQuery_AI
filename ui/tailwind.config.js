/** @type {import('tailwindcss').Config} */
/*
 * Tailwind is configured to expose the Nocturne design-system tokens (see
 * src/styles/index.css, which holds the :root variables this file points at)
 * as utility classes — bg-surface, text-neutral-500, border-divider,
 * text-accent-300, and so on. Every colour in the app comes from here or
 * from a var(--color-*) reference; nothing hard-codes a hex.
 *
 * The spacing scale is deliberately NOT remapped: Nocturne's density is
 * 0.70x, which produces fractional pixel values (2.8 / 5.6 / 8.4 / 11.2 /
 * 16.8 / 22.4). Those read more clearly as explicit arbitrary values in the
 * markup (p-[11.2px]) than as an invented alias, and they match the handoff
 * document's measurements one-to-one.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["var(--font-heading)"],
        body: ["var(--font-body)"],
      },
      colors: {
        bg: "var(--color-bg)",
        surface: "var(--color-surface)",
        ink: "var(--color-text)",
        divider: "var(--color-divider)",
        accent: {
          DEFAULT: "var(--color-accent)",
          100: "var(--color-accent-100)",
          200: "var(--color-accent-200)",
          300: "var(--color-accent-300)",
          400: "var(--color-accent-400)",
          500: "var(--color-accent-500)",
          600: "var(--color-accent-600)",
          700: "var(--color-accent-700)",
          800: "var(--color-accent-800)",
          900: "var(--color-accent-900)",
        },
        neutral: {
          100: "var(--color-neutral-100)",
          200: "var(--color-neutral-200)",
          300: "var(--color-neutral-300)",
          400: "var(--color-neutral-400)",
          500: "var(--color-neutral-500)",
          600: "var(--color-neutral-600)",
          700: "var(--color-neutral-700)",
          800: "var(--color-neutral-800)",
          900: "var(--color-neutral-900)",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        "elev-sm": "var(--shadow-sm)",
        "elev-md": "var(--shadow-md)",
        "elev-lg": "var(--shadow-lg)",
      },
      keyframes: {
        "sq-pulse": {
          "0%, 100%": { opacity: "0.35" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "sq-pulse": "sq-pulse 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
