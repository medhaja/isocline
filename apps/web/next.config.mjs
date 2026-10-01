/** API requests are proxied so the browser talks to one origin (session cookie + CSRF stay same-site). */
const API = process.env.API_INTERNAL_URL || "http://localhost:8000";

export default {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Compression would buffer Server-Sent Events from the proxied API; a reverse proxy in front
  // of the web app (nginx/Caddy) should handle compression for static assets instead.
  compress: false,
  // Fonts are bundled locally (geist package); no runtime or build-time font download.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/v1/:path*", destination: `${API}/v1/:path*` },
    ];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ],
    }];
  },
};
