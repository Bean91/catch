import { describe, expect, it } from "vitest";
import { resolveDeepLink, resolveNotificationPath } from "./deepLinkTargets";

const ctx = { hosts: ["catch.example.com"], scheme: "com.openoted.catch" };
const to = (u: string) => resolveDeepLink(u, ctx);

describe("resolveDeepLink", () => {
  it("maps the app's own https links to routes", () => {
    expect(to("https://catch.example.com/workouts/42")).toEqual({ kind: "route", to: "/workouts/42" });
    expect(to("https://catch.example.com/calendar")).toEqual({ kind: "route", to: "/calendar" });
    expect(to("https://catch.example.com/calendar/events/7")).toEqual({ kind: "route", to: "/calendar/events/7" });
    expect(to("https://catch.example.com/coach")).toEqual({ kind: "route", to: "/coach" });
    expect(to("https://catch.example.com/checkin")).toEqual({ kind: "route", to: "/checkin" });
  });

  it("ignores other hosts and other schemes", () => {
    expect(to("https://evil.example.org/workouts/1")).toBeNull();
    expect(to("http://catch.example.com/workouts/1")).toBeNull();
    expect(to("javascript:alert(1)")).toBeNull();
    expect(to("otherapp://settings/connections")).toBeNull();
    expect(to("not a url")).toBeNull();
  });

  it("falls back to Today for anything off the allow-list", () => {
    expect(to("https://catch.example.com/settings/moderation")).toEqual({ kind: "route", to: "/" });
    expect(to("https://catch.example.com/workouts/../settings/ai")).toEqual({ kind: "route", to: "/" });
    expect(to("https://catch.example.com/workouts/1%2F..%2Fadmin")).toEqual({ kind: "route", to: "/" });
    expect(to("https://catch.example.com/oauth/consent?x=1")).toEqual({ kind: "route", to: "/" });
  });

  it("keeps only the query a page reads, and the hash only for club invites", () => {
    expect(to("https://catch.example.com/workouts/3?utm=x&next=//evil")).toEqual({ kind: "route", to: "/workouts/3" });
    expect(to("https://catch.example.com/clubs/join#abc.DEF-123")).toEqual({ kind: "route", to: "/clubs/join#abc.DEF-123" });
    expect(to("https://catch.example.com/workouts/3#abc")).toEqual({ kind: "route", to: "/workouts/3" });
    expect(to("https://catch.example.com/clubs/join#<script>")).toEqual({ kind: "route", to: "/clubs/join" });
  });

  it("handles the custom-scheme OAuth return", () => {
    expect(to("com.openoted.catch://settings/connections?provider=whoop&result=ok")).toEqual({
      kind: "route",
      to: "/settings/connections?provider=whoop&result=ok",
    });
    expect(to("com.openoted.catch://settings/connections?provider=who op&result=ok")).toEqual({ kind: "route", to: "/settings/connections?result=ok" });
  });

  it("recognises a Supabase PKCE code and an auth error", () => {
    expect(to("https://catch.example.com/?code=abcdef1234567890")).toEqual({ kind: "auth", code: "abcdef1234567890" });
    expect(to("https://catch.example.com/?code=a")).toEqual({ kind: "route", to: "/" });
    expect(to("https://catch.example.com/?error=access_denied&error_description=Link+expired")).toEqual({ kind: "auth-error", message: "Link expired" });
  });
});

describe("resolveNotificationPath", () => {
  it("accepts app paths and rejects anything else", () => {
    expect(resolveNotificationPath("/calendar/events/12")).toEqual({ kind: "route", to: "/calendar/events/12" });
    expect(resolveNotificationPath("/settings/status")).toEqual({ kind: "route", to: "/settings/status" });
    expect(resolveNotificationPath("//evil.example.com/x")).toEqual({ kind: "route", to: "/" });
    expect(resolveNotificationPath("https://evil.example.com/")).toEqual({ kind: "route", to: "/" });
    expect(resolveNotificationPath(undefined)).toEqual({ kind: "route", to: "/" });
    expect(resolveNotificationPath("/")).toEqual({ kind: "route", to: "/" });
  });
});
