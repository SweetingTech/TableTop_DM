import { LogIn, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { signIn, error } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    try {
      await signIn(username, password);
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="sign-in-title">
        <div className="auth-mark"><ShieldCheck aria-hidden="true" /></div>
        <div>
          <p className="auth-label">TableTop Simulation Kernel</p>
          <h1 id="sign-in-title">Sign in</h1>
          <p className="auth-intro">Open your player, Dungeon Master, or administrator workspace.</p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>Username<input autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error ? <p className="field-error" role="alert">{error === "authentication_failed" ? "The username or password was not accepted." : error}</p> : null}
          <button className="button primary" disabled={working || !username || !password} type="submit"><LogIn aria-hidden="true" size={16} />{working ? "Signing in…" : "Sign in"}</button>
        </form>
        <p className="auth-help">First start: use <strong>admin</strong> and <strong>admin123</strong>. You will be required to choose a private password immediately.</p>
      </section>
    </main>
  );
}
