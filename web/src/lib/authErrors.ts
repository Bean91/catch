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
  // No error code and no HTTP status (or a 5xx) means the request never got a real answer from Supabase — a network
  // failure or a build with a wrong Supabase URL. Blaming the password here sends people round in circles.
  const status = e?.status ?? 0;
  if (e && typeof e === "object" && !code && (status === 0 || status >= 500)) {
    return "Can't reach the sign-in service. Check your connection and try again. If it keeps happening, the site may be misconfigured.";
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
