import { Component, ErrorInfo, ReactNode } from "react";

/** Contains a render error to one section instead of unmounting the whole app.
 *  A single throwing component (e.g. a chart library rejecting bad input) would
 *  otherwise blank the entire page. */
export default class ErrorBoundary extends Component<
  { label: string; children: ReactNode },
  { failed: boolean; message: string }
> {
  state = { failed: false, message: "" };

  static getDerivedStateFromError(error: Error) {
    return { failed: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the detail in the console for debugging; the UI stays calm.
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="section-error">
          ⚠ The {this.props.label} section couldn’t load.
          <span className="section-error-msg">{this.state.message}</span>
        </div>
      );
    }
    return this.props.children;
  }
}
