import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import Providers from "./providers";

export const metadata: Metadata = { title: "Isocline", description: "Open-source control plane and durable execution harness for AI agents" };
export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#F7F8F6" }, { media: "(prefers-color-scheme: dark)", color: "#151A1E" }],
};

/* Applies the saved theme (or the system preference) before first paint, so there is no flash of the wrong theme. */
const themeScript = `(function(){try{var p=localStorage.getItem("isc_theme")||"system";var d=p==="dark"||(p==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light"}catch(e){}})();`;

// Fonts are bundled with the app (@fontsource, SIL OFL 1.1): a self-hosted installation makes no third-party requests.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
