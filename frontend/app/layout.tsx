import type { Metadata } from "next";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import BrandLogo from "@/components/BrandLogo";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL || "http://localhost:3000"),
  title: { default: "ANI4U — كل حكاية، عالم جديد", template: "%s | ANI4U" },
  description: "اكتشف عالم الأنمي مع ANI4U. ابحث عن مسلسلاتك وأفلامك المفضلة، واستكشف المواسم والحلقات في مكان واحد.",
  applicationName: "ANI4U",
  openGraph: { type: "website", locale: "ar", siteName: "ANI4U" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl" data-scroll-behavior="smooth">
      <body>
        <a className="skip-link" href="#main-content">انتقل إلى المحتوى</a>
        <Navbar />
        <main id="main-content">{children}</main>
        <footer className="site-footer">
          <div className="page-shell footer-inner">
            <Link className="footer-brand" href="/" dir="ltr" aria-label="ANI4U — الرئيسية"><BrandLogo /></Link>
            <p>لكل حكاية عالم. اكتشف عالمك القادم.</p>
            <Link href="/search">اكتشف المزيد <span aria-hidden="true">↖</span></Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
