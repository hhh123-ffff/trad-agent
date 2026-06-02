import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15181f",
        paper: "#f7f3ec",
        steel: "#e8edf0",
        pine: "#0f5f57",
        saffron: "#c88719",
        danger: "#b53d32",
        signal: "#285f9f"
      },
      boxShadow: {
        soft: "0 18px 55px rgba(21, 24, 31, 0.11)"
      }
    }
  },
  plugins: []
};

export default config;
