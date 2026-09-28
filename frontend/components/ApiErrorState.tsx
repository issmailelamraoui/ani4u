export default function ApiErrorState({ message, title = "تعذّر تحميل المحتوى", retryHref }: { message: string; title?: string; retryHref?: string }) {
  return (
    <div className="status-panel" role="alert">
      <span className="status-symbol" aria-hidden="true">!</span>
      <div><h2>{title}</h2><p>{message}</p></div>
      {retryHref && <a className="secondary-button" href={retryHref}>إعادة المحاولة</a>}
    </div>
  );
}
