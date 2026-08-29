import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PH Flood Watch",
  description:
    "Near-real-time satellite flood mapping for the Philippines — Sentinel-2 + Prithvi foundation model, post-typhoon flood extent and exposure estimates.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
