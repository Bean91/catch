import { Link } from "react-router-dom";
import { AccountCard } from "../components/settings/AccountCard";
import { AiSharingCard } from "../components/privacy/AiSharingCard";
import { ConnectedAppsCard } from "../components/privacy/ConnectedAppsCard";
import { DeleteDataCard, ExportCard } from "../components/privacy/DataControlsCard";
import { RestrictionsCard, VisibilityCard } from "../components/privacy/VisibilityCard";
import { isPublic } from "../lib/deployment";

export function PrivacyPage() {
  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings" className="text-sm font-medium text-accent hover:underline">← Settings</Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Privacy</h1>
        <p className="mt-1 text-sm text-text-secondary">
          What Catch holds, what is shared and with whom, and your controls. These are the working controls; the written policies are drafts that
          have not had legal review —{" "}
          <Link to="/legal/privacy-policy" className="font-medium text-accent hover:underline">read the drafts</Link>.
        </p>
      </div>
      <RestrictionsCard />
      <AiSharingCard />
      <VisibilityCard />
      <ConnectedAppsCard />
      <ExportCard />
      <DeleteDataCard />
      {isPublic && <AccountCard />}
    </div>
  );
}
