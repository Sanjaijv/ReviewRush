export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xs bg-ink-900 p-3 font-mono text-[11px] leading-5 text-paper-0 rr-scrollbar">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
