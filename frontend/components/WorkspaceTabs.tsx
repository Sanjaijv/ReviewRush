"use client";

import { useRef } from "react";
import { Activity, ClipboardList, FileCode2, LayoutDashboard } from "lucide-react";
import type { WorkspaceTab } from "@/lib/dashboard-types";

const tabs: { id: WorkspaceTab; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "runs", label: "Runs", icon: Activity },
  { id: "config", label: "Config", icon: FileCode2 },
  { id: "ops", label: "Task failures & Audit log", icon: ClipboardList },
];

export function WorkspaceTabs({ activeTab, onChange, failureCount }: { activeTab: WorkspaceTab; onChange: (tab: WorkspaceTab) => void; failureCount: number }) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function moveFocus(index: number) {
    const nextIndex = (index + tabs.length) % tabs.length;
    refs.current[nextIndex]?.focus();
    onChange(tabs[nextIndex].id);
  }

  return (
    <div className="border-b border-line">
      <div role="tablist" aria-label="Repository workspace" className="rr-scrollbar flex min-w-max gap-1 overflow-x-auto">
        {tabs.map((tab, index) => {
          const Icon = tab.icon;
          const active = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              ref={(node) => { refs.current[index] = node; }}
              type="button"
              role="tab"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onKeyDown={(event) => {
                if (event.key === "ArrowRight") { event.preventDefault(); moveFocus(index + 1); }
                if (event.key === "ArrowLeft") { event.preventDefault(); moveFocus(index - 1); }
                if (event.key === "Home") { event.preventDefault(); moveFocus(0); }
                if (event.key === "End") { event.preventDefault(); moveFocus(tabs.length - 1); }
              }}
              className={`rr-focus-ring relative flex items-center gap-2 px-3 py-3 text-sm font-semibold transition ${active ? "text-accent" : "text-ink-500 hover:text-ink-900"}`}
            >
              <Icon size={15} aria-hidden="true" />
              {tab.label}
              {tab.id === "ops" && failureCount > 0 && (
                <span className="rounded-xs bg-bad/10 px-1.5 py-0.5 font-mono text-[10px] text-bad">{failureCount}</span>
              )}
              {active && <span className="absolute inset-x-2 bottom-0 h-0.5 bg-accent" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}
