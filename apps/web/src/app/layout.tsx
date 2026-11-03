import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Instrument_Sans } from "next/font/google";
import { headers } from "next/headers";
import { Footer, Header } from "@/components/chrome";
import { CapabilitiesProvider, MotionProvider, themeBootScript, WorkspaceProvider } from "@/components/providers";
import { serverCaps } from "@/lib/server";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-display-face", axes: ["wdth", "opsz"] });
const text = Instrument_Sans({ subsets: ["latin"], variable: "--font-text" });

export const metadata: Metadata = {
  title: { default: "Universal Converter: convert any file in one place", template: "%s | Universal Converter" },
  description:
    "Convert images, PDFs, Word, Excel, PowerPoint, audio, video, archives and fonts in one place. Files are deleted automatically.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f6f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0f171c" },
  ],
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const caps = await serverCaps();
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" className={`${display.variable} ${text.variable}`} suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="min-h-screen">
        <CapabilitiesProvider initial={caps}>
          <MotionProvider>
            <WorkspaceProvider>
              <Header />
              <main id="main" className="mx-auto w-full max-w-6xl px-4 sm:px-6">
                {children}
              </main>
              <Footer />
            </WorkspaceProvider>
          </MotionProvider>
        </CapabilitiesProvider>
      </body>
    </html>
  );
}
