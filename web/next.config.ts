import type { NextConfig } from "next";

// Where the UGC Studio API (FastAPI) listens. The browser only ever talks to this Next server:
// /api/* is proxied server-side (no CORS, video Range requests pass through for seeking).
// Note: rewrites are resolved when the app is built. The Docker image builds with a placeholder
// and its entrypoint swaps in the runtime UGC_API_URL (see Dockerfile / docker-entrypoint.sh).
const API_URL = (process.env.UGC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // `next dev` opened as http://127.0.0.1:3000 (not only localhost)
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // gzip would buffer the Server-Sent Events of job progress; the API is local anyway.
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
