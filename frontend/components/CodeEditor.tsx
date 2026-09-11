"use client";

import { useMemo } from "react";

export function CodeEditor({ value, onChange, error }: { value: string; onChange: (value: string) => void; error?: string | null }) {
  const lineCount = useMemo(() => Math.max(1, value.split("\n").length), [value]);
  return (
    <div className={`overflow-hidden rounded-sm border bg-ink-900 ${error ? "border-bad" : "border-ink-700"}`}>
      <div className="flex max-h-[540px] min-h-[420px] overflow-auto font-mono text-[12px] leading-6 text-paper-0 rr-scrollbar">
        <div className="select-none border-r border-ink-700 px-3 py-3 text-right text-ink-500/70" aria-hidden="true">
          {Array.from({ length: lineCount }, (_, index) => <div key={index}>{index + 1}</div>)}
        </div>
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
          aria-label="ReviewRush YAML configuration"
          aria-invalid={Boolean(error)}
          className="min-h-[420px] min-w-[620px] flex-1 resize-none bg-transparent px-4 py-3 text-paper-0 outline-hidden placeholder:text-ink-500/70"
        />
      </div>
      {error && <p className="border-t border-bad/35 bg-bad/10 px-4 py-2 text-xs text-bad" role="alert">{error}</p>}
    </div>
  );
}
