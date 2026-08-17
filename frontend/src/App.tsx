import { AppProvider } from "./app/AppContext";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { AppRouter } from "./app/AppRouter";

export function App() {
  return <ErrorBoundary><AppProvider><AppRouter /></AppProvider></ErrorBoundary>;
}
