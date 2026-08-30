"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import supabaseBrowser from "@/lib/supabase-browser";

// Week 4-9: passwordless (magic-link) login — deliberately no password field
// anywhere in this app. For a project with a handful of named users (spec.md
// §4: one admin, a small number of specific LGU/NGO viewer partners) rather
// than open public signup, magic-link avoids password-reset flows, hashing,
// and breach exposure entirely for basically zero UX cost at this scale.
// Accounts themselves aren't self-service — see docs/design-notes.md "Week
// 4-9" — a real user_roles row must already exist (provisioned directly),
// this page only lets an already-provisioned email request a sign-in link.
function LoginForm() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/admin";
  const notAdmin = searchParams.get("error") === "not_admin";

  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("sending");
    setErrorMessage(null);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}` },
    });
    if (error) {
      setStatus("error");
      setErrorMessage(error.message);
      return;
    }
    setStatus("sent");
  }

  return (
    <div style={{ maxWidth: 360, margin: "80px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>PH Flood Watch</h1>
      <p style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
        Sign in with a magic link — no password, just enter the email address your account was set up with.
      </p>

      {notAdmin && (
        <p style={{ fontSize: 13, color: "#b45309", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "8px 10px", marginBottom: 16 }}>
          That account is signed in but isn&apos;t an admin, so it can&apos;t access /admin.
        </p>
      )}

      {status === "sent" ? (
        <p style={{ fontSize: 14, color: "#166534", background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 6, padding: "10px 12px" }}>
          Check <strong>{email}</strong> for a sign-in link. It&apos;s valid for a short time — request a new one if it expires.
        </p>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input
            type="email"
            required
            placeholder="you@example.org"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 }}
          />
          <button
            type="submit"
            disabled={status === "sending"}
            style={{ padding: "8px 10px", background: "#111827", color: "#fff", border: "none", borderRadius: 6, fontSize: 14, cursor: "pointer" }}
          >
            {status === "sending" ? "Sending…" : "Send login link"}
          </button>
          {status === "error" && errorMessage && <p style={{ fontSize: 13, color: "#b91c1c" }}>{errorMessage}</p>}
        </form>
      )}
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
