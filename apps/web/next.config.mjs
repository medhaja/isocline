/**
 * Two builds of the same UI:
 *
 *  - Server (default, Docker): `output: "standalone"`. API requests are proxied so the browser talks to one origin
 *    (session cookie + CSRF stay same-site).
 *  - Static export (ISOCLINE_WEB_EXPORT=1, desktop app): `output: "export"` writes plain files to `out/`, which the
 *    API serves itself (isocline/desktop/ui.py). Rewrites, redirects and headers do not exist in a static export; the
 *    API sets the security headers and handles legacy-URL redirects there.
 */
const API = process.env.API_INTERNAL_URL || "http://localhost:8000";
// `npm run build:desktop` also selects the export (no env-var syntax in package.json, so it works on Windows too).
const EXPORT = process.env.ISOCLINE_WEB_EXPORT === "1" || process.env.npm_lifecycle_event === "build:desktop";

const common = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Compression would buffer Server-Sent Events from the proxied API; a reverse proxy in front
  // of the web app (nginx/Caddy) should handle compression for static assets instead.
  compress: false,
  // Fonts are bundled locally (@fontsource); no runtime or build-time font download.
};

const server = {
  ...common,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/v1/:path*", destination: `${API}/v1/:path*` },
    ];
  },
  // Record pages moved from /runs/<id> to /runs/view?id=<id> (static-export friendly). Keep old links working.
  async redirects() {
    return ["runs", "workflows", "projects", "evaluations"].map((section) => ({
      source: `/${section}/:id((?!view$|compare$)[^/]+)`,
      destination: `/${section}/view?id=:id`,
      permanent: false,
    }));
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

const staticExport = {
  ...common,
  output: "export",
  images: { unoptimized: true },
};

export default EXPORT ? staticExport : server;
