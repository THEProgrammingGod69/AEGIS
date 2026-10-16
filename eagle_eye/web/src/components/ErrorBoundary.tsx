import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component, type ReactNode } from "react";

/** Keeps a rendering bug on one page from blanking the whole console during a live demo. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="main">
        <div className="card pad empty">
          <AlertTriangle style={{ color: "var(--review)", opacity: 1 }} />
          <div>This view hit an unexpected error: <span className="mono small">{this.state.error.message}</span></div>
          <div className="row">
            <button className="btn" onClick={() => this.setState({ error: null })}><RotateCcw /> Try again</button>
            <a className="btn btn-primary" href="#/inspect">New inspection</a>
          </div>
        </div>
      </div>
    );
  }
}
