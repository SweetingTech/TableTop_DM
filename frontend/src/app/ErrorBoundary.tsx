import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Frontend boundary", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="fatal-error" role="alert">
          <h1>The instrument panel stopped responding.</h1>
          <p>{this.state.error.message}</p>
          <button className="button primary" type="button" onClick={() => window.location.reload()}>
            Reload workspace
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
