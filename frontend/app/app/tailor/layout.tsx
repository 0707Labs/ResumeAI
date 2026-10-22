import { ClearAll, StepNav } from "@/components/AppShell";

/** The tailoring flow: its step bar, and clearing what this tab holds. */
export default function TailorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <div className="-mt-2 mb-6 flex flex-wrap items-center justify-between gap-2 border-b border-border">
        <div className="min-w-0 flex-1"><StepNav /></div>
        <div className="pb-2"><ClearAll /></div>
      </div>
      {children}
    </>
  );
}
