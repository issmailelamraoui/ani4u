"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => { console.error("[NOVA] Page rendering failed", error); }, [error]);
  return <div className="page-shell route-message" role="alert"><span className="eyebrow">NOVA ANIME</span><h1>تعذّر عرض هذه الصفحة</h1><p>حدث خطأ أثناء تحميل المحتوى. يرجى المحاولة مجددًا.</p><button className="primary-button" onClick={() => retry()}>إعادة المحاولة</button></div>;
}
