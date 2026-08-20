import { AppProvider } from "./app/AppContext";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { AppRouter } from "./app/AppRouter";
import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import { ChangePasswordPage } from "./features/auth/ChangePasswordPage";
import { LoginPage } from "./features/auth/LoginPage";
import { LoadingState } from "./components/ui/States";

function AuthenticatedApplication() {
  const { user, loading } = useAuth();
  if (loading) return <main className="auth-page"><LoadingState label="Checking your account" /></main>;
  if (!user) return <LoginPage />;
  if (user.password_change_required) return <ChangePasswordPage />;
  return <AppProvider><AppRouter /></AppProvider>;
}

export function App() {
  return <ErrorBoundary><AuthProvider><AuthenticatedApplication /></AuthProvider></ErrorBoundary>;
}
