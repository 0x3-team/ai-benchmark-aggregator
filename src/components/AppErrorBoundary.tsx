import { Component, createRef, type ErrorInfo, type ReactNode } from "react";

interface AppErrorBoundaryProps {
  /** A selected immutable dataset snapshot. Changing it retries rendering. */
  readonly resetKey: unknown;
  readonly sourceLabel: string;
  readonly children: ReactNode;
}

interface AppErrorBoundaryState {
  readonly hasError: boolean;
}

/**
 * Contains failures while an immutable dataset snapshot is being constructed
 * or rendered. It deliberately sits outside DatasetProvider so a malformed
 * selected source can never trigger a hidden fallback to Demo data.
 */
export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { hasError: false };

  private readonly headingRef = createRef<HTMLHeadingElement>();

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _errorInfo: ErrorInfo): void {
    this.headingRef.current?.focus();
  }

  componentDidUpdate(previousProps: AppErrorBoundaryProps): void {
    if (previousProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  private retry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <main
        id="main-content"
        role="alert"
        aria-labelledby="dataset-error-title"
        className="mx-auto flex min-h-[50vh] max-w-2xl flex-col justify-center gap-4 px-4 py-12 sm:px-6"
      >
        <h1
          id="dataset-error-title"
          ref={this.headingRef}
          tabIndex={-1}
          className="text-xl font-semibold tracking-tight text-foreground"
        >
          Data display unavailable
        </h1>
        <p className="text-sm text-muted-foreground">
          The selected {this.props.sourceLabel} dataset could not be displayed. No fallback dataset was selected.
        </p>
        <div>
          <button
            type="button"
            onClick={this.retry}
            className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-ring"
          >
            Try again
          </button>
        </div>
      </main>
    );
  }
}
