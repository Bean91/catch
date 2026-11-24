import { Link, useParams } from "react-router-dom";
import { renderMarkdown } from "../lib/miniMarkdown";

// The drafts live in docs/legal/*.md (the one source of truth, also read as plain files). Vite inlines them at build time.
const DOCS = import.meta.glob("../../../docs/legal/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const byName: Record<string, string> = Object.fromEntries(Object.entries(DOCS).map(([path, text]) => [path.split("/").pop()!.replace(/\.md$/, ""), text]));

const TITLES: Record<string, string> = {
  "privacy-policy": "Privacy policy",
  "terms-of-service": "Terms of service",
  "data-deletion-policy": "Data deletion",
  "account-deletion": "Delete your account",
  "ai-data-sharing": "AI data sharing",
  "provider-disclosures": "Provider integrations",
  "not-medical-advice": "Not medical advice",
  "community-guidelines": "Community guidelines",
};

// `publicDoc`: rendered outside the sign-in gate (App.tsx) for the pages a store listing links to without an account.
export function LegalPage({ publicDoc }: { publicDoc?: string } = {}) {
  const params = useParams();
  const doc = publicDoc ?? params.doc ?? "privacy-policy";
  const text = byName[doc];
  return (
    <div className="flex flex-col gap-4 lg:gap-5" data-testid="legal-page">
      <div>
        <Link to={publicDoc ? "/" : "/settings/privacy"} className="text-sm font-medium text-accent hover:underline">{publicDoc ? "← Catch" : "← Privacy"}</Link>
      </div>
      <nav aria-label="Documents" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {Object.entries(TITLES).map(([slug, title]) => (
          <Link key={slug} to={`/legal/${slug}`} aria-current={slug === doc ? "page" : undefined} className={slug === doc ? "font-semibold text-text-primary" : "font-medium text-accent hover:underline"}>
            {title}
          </Link>
        ))}
      </nav>
      <article className="glass-secondary flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 sm:p-5">
        {text ? renderMarkdown(text) : <p className="text-sm text-text-secondary">No such document.</p>}
      </article>
    </div>
  );
}
