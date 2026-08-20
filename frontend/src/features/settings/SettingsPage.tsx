import { useState, type FormEvent } from "react";
import {
  CheckCircle2,
  Database,
  KeyRound,
  LogOut,
  Radio,
  Save,
  ServerCog,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import {
  DefinitionList,
  PageHeader,
  Panel,
  Stat,
  Status,
} from "../../components/ui/Primitives";
import {
  ErrorState,
  LoadingState,
  SourceNotice,
} from "../../components/ui/States";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { useAuth } from "../auth/AuthContext";
import { updateProfile } from "../auth/api";
import type { UserProfile } from "../auth/types";
import { loadSettings, updateTelemetry } from "./api";

export default function SettingsPage() {
  const { user, setUser, changePassword, signOut } = useAuth();
  const resource = useAsyncResource(() => loadSettings(Boolean(user?.is_admin)), [user?.is_admin]);
  const [profile, setProfile] = useState<UserProfile>(() => user!.profile);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [telemetryOverride, setTelemetryOverride] = useState<boolean | null>(
    null,
  );
  const [working, setWorking] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const payload = resource.data?.data;
  const telemetryEnabled =
    telemetryOverride ?? payload?.telemetry.human_telemetry_enabled ?? false;


  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setWorking("profile");
    setError("");
    setMessage("");
    try {
      const account = await updateProfile(profile);
      setUser(account);
      setMessage("Profile saved.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Profile update failed",
      );
    } finally {
      setWorking("");
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (newPassword !== confirmation) {
      setError("The new passwords do not match.");
      return;
    }
    setWorking("password");
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setMessage("Password changed. Other sessions were signed out.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Password change failed",
      );
    } finally {
      setWorking("");
    }
  }

  async function changeTelemetry(enabled: boolean) {
    const previous = telemetryEnabled;
    setTelemetryOverride(enabled);
    setWorking("telemetry");
    setError("");
    setMessage("");
    try {
      const result = await updateTelemetry(enabled);
      setTelemetryOverride(result.data.human_telemetry_enabled);
      setMessage(
        result.data.human_telemetry_enabled
          ? "Local human telemetry enabled."
          : "Human telemetry disabled.",
      );
    } catch (reason) {
      setTelemetryOverride(previous);
      setError(
        reason instanceof Error ? reason.message : "Telemetry update failed",
      );
    } finally {
      setWorking("");
    }
  }

  return (
    <div className="page settings-page">
      {resource.data ? (
        <SourceNotice
          source={resource.data.source}
          reason={resource.data.reason}
        />
      ) : null}
      <PageHeader
        title="Settings"
        description="Manage your profile, sign-in security, preferences, and local simulation settings."
        actions={
          <button
            className="button"
            type="button"
            onClick={() => void signOut()}
          >
            <LogOut size={15} />
            Sign out
          </button>
        }
      />
      {message || error ? (
        <div
          className={`toast ${error ? "error" : "success"}`}
          role={error ? "alert" : "status"}
        >
          {error || message}
        </div>
      ) : null}
      <div className="settings-layout account-settings-layout">
        <Panel
          title="Personal information"
          meta={<UserRound size={17} />}
          className="settings-profile"
        >
          <form className="profile-form" onSubmit={saveProfile}>
            <div className="form-pair">
              <label>
                Display name
                <input
                  value={profile.display_name}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      display_name: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Legal name
                <input
                  value={profile.legal_name ?? ""}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      legal_name: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <div className="form-pair">
              <label>
                Username
                <input value={user?.username ?? ""} disabled />
                <small>Administrators can change usernames.</small>
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={profile.email ?? ""}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      email: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <div className="form-pair">
              <label>
                Date of birth
                <input
                  type="date"
                  value={profile.date_of_birth ?? ""}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      date_of_birth: event.target.value || null,
                    }))
                  }
                />
              </label>
              <label>
                Pronouns
                <input
                  value={profile.pronouns ?? ""}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      pronouns: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <div className="form-pair">
              <label>
                Timezone
                <input
                  value={profile.timezone}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      timezone: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Locale
                <input
                  value={profile.locale}
                  onChange={(event) =>
                    setProfile((current) => ({
                      ...current,
                      locale: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <label>
              About you
              <textarea
                value={profile.bio ?? ""}
                onChange={(event) =>
                  setProfile((current) => ({
                    ...current,
                    bio: event.target.value,
                  }))
                }
              />
            </label>
            <button
              className="button primary"
              disabled={working === "profile" || !profile.display_name}
              type="submit"
            >
              <Save size={15} />
              {working === "profile" ? "Saving…" : "Save profile"}
            </button>
          </form>
        </Panel>
        <Panel
          title="Password and security"
          meta={<KeyRound size={17} />}
          className="settings-security"
        >
          <p className="panel-intro">
            Changing your password closes every other signed-in session. Use at
            least 12 characters.
          </p>
          <form className="password-form" onSubmit={savePassword}>
            <label>
              Current password
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </label>
            <label>
              New password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </label>
            <label>
              Confirm new password
              <input
                type="password"
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </label>
            <button
              className="button"
              disabled={
                working === "password" ||
                !currentPassword ||
                newPassword.length < 12 ||
                newPassword !== confirmation
              }
              type="submit"
            >
              <KeyRound size={15} />
              {working === "password" ? "Changing…" : "Change password"}
            </button>
          </form>
          <DefinitionList
            items={[
              [
                "Account type",
                user?.is_admin ? "Administrator" : "Standard account",
              ],
              [
                "Dungeon Master",
                user?.has_dm_role ? "Enabled" : "Not assigned",
              ],
              ["Player", user?.has_player_role ? "Enabled" : "Not assigned"],
            ]}
          />
        </Panel>
        <Panel
          title="Engine health"
          meta={
            <span className="safe">
              <CheckCircle2 size={15} />
              Contract available
            </span>
          }
          className="settings-engine"
        >
          {resource.loading && !payload ? (
            <LoadingState label="Loading local settings" />
          ) : resource.error && !payload ? (
            <ErrorState message={resource.error} retry={resource.reload} />
          ) : payload ? (
            <>
              <div className="stat-strip">
                <Stat label="Kernel" value={payload.meta.kernel} />
                <Stat label="Contract" value={payload.meta.contract_version} />
                <Stat
                  label="Persona schema"
                  value={payload.meta.persona_schema_version}
                />
                <Stat
                  label="Dimensions"
                  value={payload.meta.persona_dimensions}
                />
              </div>
              <div className="diagnostic-grid">
                <div>
                  <ServerCog />
                  <strong>Simulation engine</strong>
                  <span>
                    {resource.data?.source === "live"
                      ? "Responding"
                      : "Endpoint unavailable"}
                  </span>
                </div>
                <div>
                  <Database />
                  <strong>Storage</strong>
                  <span>Durable account and world stores</span>
                </div>
                <div>
                  <Radio />
                  <strong>Session</strong>
                  <span>Secure HTTP-only cookie</span>
                </div>
                <div>
                  <ShieldCheck />
                  <strong>Authorization</strong>
                  <span>Account and world roles</span>
                </div>
              </div>
            </>
          ) : null}
        </Panel>
        {user?.is_admin ? (
          <Panel
            title="Telemetry"
            meta={<Status value={telemetryEnabled ? "ENABLED" : "DISABLED"} />}
            className="settings-telemetry"
          >
            <label className="switch-row">
              <span>
                <strong>Human telemetry</strong>
                <small>
                  Capture consented playtest measurements for local calibration.
                </small>
              </span>
              <input
                aria-busy={working === "telemetry"}
                aria-label="Human telemetry"
                data-testid="telemetry-setting"
                type="checkbox"
                checked={telemetryEnabled}
                disabled={!payload || Boolean(resource.error)}
                onChange={(event) => void changeTelemetry(event.target.checked)}
              />
            </label>
            <DefinitionList
              items={[
                [
                  "Location",
                  payload?.telemetry.local_only
                    ? "Local machine only"
                    : "External sink configured",
                ],
                ["Default", "Disabled"],
                ["Synthetic label", "Hypothesis, never human ground truth"],
              ]}
            />
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
