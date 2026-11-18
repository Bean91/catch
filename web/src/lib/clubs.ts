// Labels only. The browser holds no permission, scoring or age logic: the server returns what each role may do (`capabilities`, `can_*`) and every
// figure it shows. These are the words around them.
import type { ClubChallengeRow } from "./types";

export const REPORT_REASONS_CLUB = [
  { value: "harassment", label: "Bullying or harassment" },
  { value: "unsafe", label: "Something unsafe" },
  { value: "inappropriate", label: "Inappropriate content" },
  { value: "impersonation", label: "Pretending to be someone" },
  { value: "spam", label: "Spam" },
  { value: "other", label: "Something else" },
] as const;

export const SESSION_TYPES = [
  { value: "erg", label: "Erg" }, { value: "on_water", label: "On the water" }, { value: "run", label: "Run" }, { value: "bike", label: "Bike" },
  { value: "strength", label: "Strength" }, { value: "cross", label: "Cross-training" }, { value: "test", label: "Test" }, { value: "other", label: "Other" },
] as const;

export function metricLabel(metric: ClubChallengeRow["metric"]): string {
  return { distance: "Distance (capped)", time: "Time trained (capped)", sessions: "Number of sessions", tests: "Erg tests completed", consistency: "Consistency (weeks)" }[metric];
}

export function phaseLabel(phase: string): string {
  return { upcoming: "Starts soon", open: "Open", grace: "Settling", closed: "Final", pending: "Waiting for approval", cancelled: "Cancelled", rejected: "Not approved" }[phase] ?? phase;
}

export const CLUB_ACTION_LABEL: Record<string, string> = {
  club_created: "Club created", club_updated: "Settings changed", member_joined: "Joined", member_left: "Left", member_removed: "Removed", role_changed: "Role changed", ownership_transferred: "Ownership handed over",
  invite_created: "Invite created", invite_revoked: "Invite revoked", request_approved: "Request approved", request_rejected: "Request declined", post_created: "Post created", post_auto_hidden: "Post hidden after reports",
  announcement_approved: "Post approved", announcement_rejected: "Post declined", announcement_taken_down: "Post taken down", session_created: "Session planned", challenge_created: "Challenge created",
  result_hidden: "Result hidden", logo_changed: "Logo changed", logo_removed: "Logo removed", moderator_suspend_club: "Suspended by a platform moderator", moderator_restore_club: "Restored by a platform moderator",
  moderator_remove_member: "Removed by a platform moderator", moderator_hide_announcement: "Post hidden by a platform moderator", ownership_transferred_on_account_deletion: "Ownership passed on (account deleted)",
  club_deleted_owner_left_no_successor: "Club closed (owner's account deleted)", migration_member_not_carried: "Not carried over from the old club",
};
