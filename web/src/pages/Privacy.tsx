import { Link } from "react-router-dom";
import { PageHeader, SectionHeader } from "../components/ui/PageHeader";
import { AccountCard } from "../components/settings/AccountCard";
import { AiSharingCard } from "../components/privacy/AiSharingCard";
import { ConnectedAppsCard } from "../components/privacy/ConnectedAppsCard";
import { DeleteDataCard, ExportCard } from "../components/privacy/DataControlsCard";
import { RestrictionsCard, VisibilityCard } from "../components/privacy/VisibilityCard";
import { isPublic } from "../lib/deployment";

export function PrivacyPage() {
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        back={{ to: "/settings", label: "Settings" }}
        eyebrow="Sharing and visibility"
        title="Privacy"
        subtitle={
          <>
            What Catch holds, what is shared and with whom, and your controls. These are the working controls; the written policies are drafts that have
            not had legal review —{" "}
            <Link to="/legal/privacy-policy" className="font-medium text-accent hover:underline">
              read the drafts
            </Link>
            .
          </>
        }
      />
      <RestrictionsCard />
      <SectionHeader title="Sharing" description="What an AI may see, and what other people can see." />
      <AiSharingCard />
      <VisibilityCard />
      <ConnectedAppsCard />
      <SectionHeader title="Your data" description="Take a copy, or delete parts of it. Each delete says what it removes first." />
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">
        <ExportCard />
        <DeleteDataCard />
      </div>
      {isPublic && <AccountCard />}
    </div>
  );
}
