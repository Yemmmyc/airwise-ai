import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AIRWISE AI | Urban Air Quality Intelligence Assistant",
  description:
    "Urban Air Quality Assistant providing model-based AQI monitoring, pollutant explanations, historical trends, deterministic risk windows, and grounded Gemini guidance for daily family planning.",
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
