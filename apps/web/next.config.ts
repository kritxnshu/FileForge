import type { NextConfig } from "next";

// The Content-Security-Policy is set per request (with a nonce) in src/proxy.ts.
// Uploaded/converted content is never rendered on this origin: previews use <img>/<audio>/<video> or escaped
// text, and the API serves SVG/HTML downloads with `CSP: sandbox`.

const nextConfig: NextConfig = {
  poweredByHeader: false,
  output: "standalone",
  // Tailwind v4 via its Turbopack loader (no PostCSS config needed).
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
