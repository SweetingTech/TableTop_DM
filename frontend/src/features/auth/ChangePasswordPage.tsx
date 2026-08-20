import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "./AuthContext";

export function ChangePasswordPage() {
  const { user, changePassword, error } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [working, setWorking] = useState(false);
  const mismatch = confirmation.length > 0 && confirmation !== newPassword;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (mismatch) return;
    setWorking(true);
    try {
      await changePassword(currentPassword, newPassword);
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="change-password-title">
        <div className="auth-mark"><KeyRound aria-hidden="true" /></div>
        <div>
          <p className="auth-label">Welcome, {user?.profile.display_name}</p>
          <h1 id="change-password-title">Protect the administrator account</h1>
          <p className="auth-intro">The shared first-start password cannot access the application. Choose a private password to continue.</p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
          <label>New password<input type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
          <label>Confirm new password<input type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          {mismatch ? <p className="field-error" role="alert">The new passwords do not match.</p> : null}
          {error ? <p className="field-error" role="alert">{error}</p> : null}
          <button className="button primary" disabled={working || currentPassword.length === 0 || newPassword.length < 12 || mismatch} type="submit">{working ? "Saving…" : "Change password and continue"}</button>
        </form>
      </section>
    </main>
  );
}
