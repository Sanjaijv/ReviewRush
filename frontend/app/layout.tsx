import type { Metadata } from "next";
import { Archivo, JetBrains_Mono, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
});

const sourceSans = Source_Sans_3({
  variable: "--font-source-sans",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["500", "600"],
});

export const metadata: Metadata = {
  title: "ReviewRush · Code review operations",
  description: "Review runs, configuration, and audit history for ReviewRush-managed repositories.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${sourceSans.variable} ${jetbrains.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-paper-0 text-ink-900">
        <AuthProvider>
          <main className="min-h-screen">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
