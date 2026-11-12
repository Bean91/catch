// Plain-language messages for Supabase Auth failures. Deliberately never reveals whether an email is registered:
// sign-in failures are one message, and "reset password" always says the same thing.
export function describeAuthError(err: unknown, context: "signin" | "signup" | "reset" | "update"): string {
  const e = err as { code?: string; status?: number; message?: string } | null;
  const code = e?.code ?? "";
  if (code === "email_not_confirmed") return "Confirm your email first — we sent you a link.";
  if (code === "over_email_send_rate_limit" || code === "over_request_rate_limit" || e?.status === 429) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (code === "weak_password") return "That password is too weak. Use at least 8 characters.";
  if (code === "user_already_exists" || code === "email_exists") {
    return "Could not create the account. If you already have one, sign in or reset your password.";
  }
  if (context === "signin") return "Incorrect email or password.";
  if (context === "signup") return "Could not create the account. Check the details and try again.";
  if (context === "update") return "Could not update the password. The link may have expired — request a new one.";
  return "Could not send the email. Try again in a minute.";
}

export function passwordProblem(password: string): string | null {
  if (password.length < 8) return "Use at least 8 characters.";
  return null;
}
