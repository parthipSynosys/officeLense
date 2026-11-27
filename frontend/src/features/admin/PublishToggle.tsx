/** Accessible on/off switch for publishing an event. */
export function PublishToggle({
  published,
  onChange,
  disabled,
  label,
}: {
  published: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={published}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!published)}
      className="inline-flex items-center gap-2 rounded-xl text-sm font-semibold disabled:opacity-50"
    >
      <span className={`relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors ${published ? "bg-success" : "bg-line-strong"}`}>
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow-soft transition-transform ${published ? "translate-x-[22px]" : "translate-x-0.5"}`}
        />
      </span>
      <span className={published ? "text-success" : "text-ink-muted"}>{published ? "Published" : "Draft"}</span>
    </button>
  );
}
