import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIRWISE AI | Urban Air Quality Intelligence Assistant",
  description:
    "Environmental intelligence dashboard for urban air quality monitoring, pollutant insights, health advisories, and daily planning recommendations (Day 1 Demo Foundation).",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-theme-main text-theme-text antialiased selection:bg-theme-accent selection:text-[#0B1415]">
        {children}
      </body>
    </html>
  );
}
