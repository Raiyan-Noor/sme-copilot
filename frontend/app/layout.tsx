import type { Metadata } from "next";

import { AdvisorApp } from "@/components/advisor/shell";
import { APP_NAME, APP_TAGLINE } from "@/config/app";
import "./globals.css";

export const metadata: Metadata = {
  title: APP_NAME,
  description: APP_TAGLINE,
};

/**
 * One conversation-first screen for every route. The routes (Today, Ask, Cash flow, Financing, Inbox, Trust) stay
 * as deep links: the app reads the path and opens the matching view, so pages render nothing themselves.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <AdvisorApp />
        {children}
      </body>
    </html>
  );
}
