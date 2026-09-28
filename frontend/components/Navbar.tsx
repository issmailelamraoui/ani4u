import Link from "next/link";
import BrandLogo from "@/components/BrandLogo";
import { SearchIcon } from "@/components/Icons";

export default function Navbar() {
  return (
    <header className="site-header">
      <div className="nav-container">
        <Link href="/" className="brand" aria-label="ANI4U — الرئيسية">
          <BrandLogo header />
        </Link>
        <nav className="desktop-nav" aria-label="التنقل الرئيسي">
          <Link href="/">الرئيسية</Link>
          <Link href="/#discover">اكتشف الأنمي</Link>
          <Link href="/search">تصفح المكتبة</Link>
        </nav>
        <Link href="/search" className="search-button"><SearchIcon /><span>ابحث عن أنمي</span></Link>
      </div>
    </header>
  );
}
