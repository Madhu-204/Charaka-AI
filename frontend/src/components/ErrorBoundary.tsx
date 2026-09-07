import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Charaka AI render error:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: "center" }} className="reasoning-panel empty-state">
          <h3 style={{ marginBottom: 10, color: "var(--danger)" }}>
            Something went wrong while rendering.
          </h3>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {this.state.error.message}
          </p>
          <button
            className="btn"
            style={{ marginTop: 16 }}
            onClick={() => {
              location.reload();
            }}
          >
            Reload app
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}