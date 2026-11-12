import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // `make dev` is opened from phones on the home LAN (http://<lan-ip>:3000): allow private-LAN origins
  // to load dev assets/HMR. Dev server only; the production static export is served by FastAPI.
  allowedDevOrigins: ["192.168.*.*", "10.*.*.*", "**.local", "**.lan", "**.home"],
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
