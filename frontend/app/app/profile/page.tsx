"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PersonalTab } from "@/components/app/profile/PersonalTab";
import { PreferencesTab } from "@/components/app/profile/PreferencesTab";
import { PrivacyTab } from "@/components/app/profile/PrivacyTab";
import { ResumeTab } from "@/components/app/profile/ResumeTab";
import { PageHeader } from "@/components/app/states";
import { TabList, TabPanel, useTab } from "@/components/app/Tabs";

const TABS = ["personal", "preferences", "resume", "privacy"] as const;
const LABELS = { personal: "Personal", preferences: "Job preferences", resume: "Resume details", privacy: "Privacy" };

export default function ProfilePage() {
  return (
    <Suspense fallback={null}>
      <Profile />
    </Suspense>
  );
}

function Profile() {
  const params = useSearchParams();
  // Returning from connecting Google/GitHub (?linked= / ?error=) lands on Personal.
  const [tab, setTab] = useTab(TABS, "personal");
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Profile" intro="Your details, what you're looking for, your base resumes and your privacy choices." />
      <TabList label="Profile sections" tabs={TABS} labels={LABELS} current={tab} onSelect={setTab} idPrefix="profile" />
      <TabPanel id={tab} idPrefix="profile">
        {tab === "personal" && <PersonalTab linked={params.get("linked")} error={params.get("error")} />}
        {tab === "preferences" && <PreferencesTab />}
        {tab === "resume" && <ResumeTab />}
        {tab === "privacy" && <PrivacyTab />}
      </TabPanel>
    </div>
  );
}
