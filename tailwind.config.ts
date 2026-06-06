import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        paper: "#eef2f4",
        steel: "#dbe3ea",
        pine: "#0f5f57",
        saffron: "#c88719",
        danger: "#b53d32",
        signal: "#285f9f"
      },
      boxShadow: {
        soft: "0 10px 30px rgba(17, 24, 39, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
