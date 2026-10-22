"use client";

import { useId, useState } from "react";

import { Label, inputClass } from "@/components/ui";
import { EMPLOYMENT_TYPES, type PreferencesIn, SENIORITY, WORK_MODES } from "@/lib/schemas";
import { EMPLOYMENT_LABEL, NOTICE_OPTIONS, SENIORITY_LABEL, WORK_MODE_LABEL } from "@/lib/user";

export const EMPTY_PREFERENCES: PreferencesIn = {
  target_roles: [], seniority: null, industries: [], locations: [], work_modes: [], employment_types: [],
  notice_period_days: null,
};

/** Job preferences fields (onboarding step 2 and the profile tab). Controlled. */
export function PreferencesForm({ value, onChange }: { value: PreferencesIn; onChange: (v: PreferencesIn) => void }) {
  const id = useId();
  const set = <K extends keyof PreferencesIn>(key: K, v: PreferencesIn[K]) => onChange({ ...value, [key]: v });
  const toggle = <T extends string>(list: T[], item: T) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  return (
    <div className="space-y-5">
      <ListInput id={`${id}-roles`} label="Target roles" hint="(up to 10)" placeholder="e.g. Data Analyst"
        values={value.target_roles} onChange={(v) => set("target_roles", v)} />
      <div>
        <Label htmlFor={`${id}-seniority`}>Seniority</Label>
        <select id={`${id}-seniority`} className={inputClass} value={value.seniority ?? ""}
          onChange={(e) => set("seniority", (e.target.value || null) as PreferencesIn["seniority"])}>
          <option value="">Not sure yet</option>
          {SENIORITY.map((s) => <option key={s} value={s}>{SENIORITY_LABEL[s]}</option>)}
        </select>
      </div>
      <ListInput id={`${id}-industries`} label="Industries" placeholder="e.g. Fintech"
        values={value.industries} onChange={(v) => set("industries", v)} />
      <ListInput id={`${id}-locations`} label="Locations" placeholder="e.g. Bengaluru"
        values={value.locations} onChange={(v) => set("locations", v)} />
      <fieldset>
        <legend className="text-sm font-medium text-fg">Work setup</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {WORK_MODES.map((m) => (
            <Check key={m} label={WORK_MODE_LABEL[m]} checked={value.work_modes.includes(m)}
              onChange={() => set("work_modes", toggle(value.work_modes, m))} />
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="text-sm font-medium text-fg">Employment type</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {EMPLOYMENT_TYPES.map((t) => (
            <Check key={t} label={EMPLOYMENT_LABEL[t]} checked={value.employment_types.includes(t)}
              onChange={() => set("employment_types", toggle(value.employment_types, t))} />
          ))}
        </div>
      </fieldset>
      <div>
        <Label htmlFor={`${id}-notice`}>Notice period</Label>
        <select id={`${id}-notice`} className={inputClass} value={value.notice_period_days ?? ""}
          onChange={(e) => set("notice_period_days", e.target.value === "" ? null : Number(e.target.value))}>
          {NOTICE_OPTIONS.map((o) => <option key={o.label} value={o.value ?? ""}>{o.label}</option>)}
        </select>
      </div>
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <label className={`flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${
      checked ? "border-accent bg-accent-soft text-fg" : "border-border-strong text-muted hover:text-fg"}`}>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 accent-accent" />
      {label}
    </label>
  );
}

/** Free-text entries as removable chips: type and press Enter or comma, or Add. */
export function ListInput({ id, label, hint, placeholder, values, onChange, max = 10, maxLength = 80 }: {
  id: string; label: string; hint?: string; placeholder: string; values: string[]; onChange: (v: string[]) => void;
  max?: number; maxLength?: number;
}) {
  const [draft, setDraft] = useState("");
  const full = values.length >= max;
  const add = () => {
    const v = draft.replace(/,/g, " ").split(/\s+/).join(" ").trim().slice(0, maxLength);
    if (v && !full && !values.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...values, v]);
    setDraft("");
  };
  return (
    <div>
      <Label htmlFor={id} hint={hint}>{label}</Label>
      {values.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={label}>
          {values.map((v) => (
            <li key={v} className="flex items-center gap-1 rounded-full bg-surface-2 py-1 pl-3 pr-1 text-sm text-fg">
              {v}
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))}
                className="flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-border hover:text-fg"
                aria-label={`Remove ${v}`}>×</button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input id={id} className={inputClass} value={draft} placeholder={full ? "That's the most we keep" : placeholder}
          disabled={full} maxLength={maxLength} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} onBlur={add} />
        <button type="button" onClick={add} disabled={!draft.trim() || full}
          className="mt-1.5 min-h-10 rounded-lg border border-border-strong px-3 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50">
          Add
        </button>
      </div>
    </div>
  );
}
