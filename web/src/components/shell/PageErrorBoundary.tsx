import { Component, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

interface Props {
  children: ReactNode;
  resetKey: string;
}

interface State {
  error: Error | null;
}

// Without a boundary, React unmounts the whole tree when one page throws, so the navigation went with it and the app was a blank
// screen with no way out (a stale cached settings shape on a native build did exactly that). The page area shows an error instead;
// navigating elsewhere clears it.
class Boundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("Page crashed:", error);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-band-red/40 px-4 py-8 text-center" data-testid="page-error">
        <p className="text-sm font-medium text-text-primary">This page hit a problem and couldn't be shown.</p>
        <p className="max-w-md text-xs text-text-tertiary">{this.state.error.message}</p>
        <div className="flex flex-wrap justify-center gap-3">
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary hover:border-accent"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary hover:border-accent"
          >
            Reload the app
          </button>
        </div>
      </div>
    );
  }
}

export function PageErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <Boundary resetKey={pathname}>{children}</Boundary>;
}
