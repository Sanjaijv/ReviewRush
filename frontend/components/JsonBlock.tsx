export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="bg-neutral-100 rounded p-3 text-xs overflow-auto max-h-96">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
