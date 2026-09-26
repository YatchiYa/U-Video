import type { Metadata, Viewport } from "next";
import { Header } from "@/components/Header";
import { ToastProvider } from "@/components/ui";
import { I18nProvider } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "UGC Studio",
  description: "Local AI video production: create, fix and export your videos.",
};

export const viewport: Viewport = {
  themeColor: "#f7f5f1",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className="h-full">
      <body className="flex min-h-full flex-col">
        <I18nProvider>
          <ToastProvider>
            <Header />
            <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 pb-24 pt-6 sm:px-6 sm:pt-8">
              {children}
            </main>
          </ToastProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
