import type { Metadata, Viewport } from "next";
import { Geist, Inter, JetBrains_Mono } from "next/font/google";
import { headers } from "next/headers";
import { CommandPalette } from "@/components/CommandPalette";
import { Footer, Shell } from "@/components/chrome";
import { CapabilitiesProvider, MotionProvider, themeBootScript, WorkspaceProvider } from "@/components/providers";
import { serverCaps } from "@/lib/server";
import "./globals.css";

const display = Geist({ subsets: ["latin"], variable: "--font-display-face" });
const text = Inter({ subsets: ["latin"], variable: "--font-text" });
const code = JetBrains_Mono({ subsets: ["latin"], variable: "--font-code" });

export const metadata: Metadata = {
  title: { default: "FileForge: convert any file in one place", template: "%s | FileForge" },
  description:
    "Convert images, PDFs, Word, Excel, PowerPoint, audio, video, archives and fonts in one place. Files are deleted automatically.",
  icons: { icon: { url: "/logo.svg", type: "image/svg+xml" } }, // app/favicon.ico is linked automatically
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const caps = await serverCaps();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" className={`${display.variable} ${text.variable} ${code.variable}`} suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="min-h-screen">
        <CapabilitiesProvider initial={caps}>
          <MotionProvider>
            <WorkspaceProvider>
              <Shell>
                <main id="main" className="mx-auto w-full max-w-[1240px] px-4 pb-10 pt-5 sm:px-6 lg:px-8">
                  {children}
                </main>
                <Footer />
              </Shell>
              <CommandPalette />
            </WorkspaceProvider>
          </MotionProvider>
        </CapabilitiesProvider>
      </body>
    </html>
  );
}
