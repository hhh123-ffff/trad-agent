import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111713",
        paper: "#f4efe4",
        steel: "#dce5df",
        pine: "#0b6b5f",
        saffron: "#b8792d",
        danger: "#b74235",
        signal: "#1f5f8a"
      },
      boxShadow: {
        soft: "0 18px 55px rgba(17, 23, 19, 0.13)",
        terminal: "0 28px 90px rgba(10, 27, 24, 0.16)"
      }
    }
  },
  plugins: []
};

export default config;
