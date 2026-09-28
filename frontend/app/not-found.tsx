import Link from "next/link";

export default function NotFound() {
  return <div className="page-shell route-message"><span className="eyebrow">404</span><h1>هذا العالم غير موجود</h1><p>قد يكون الرابط غير صحيح، أو لم يعد العنوان متاحًا.</p><Link className="primary-button" href="/search">ابحث عن أنمي آخر</Link></div>;
}
