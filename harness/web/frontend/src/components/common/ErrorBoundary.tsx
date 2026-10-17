import React from "react";

/** Любая ошибка рендера становится видимой — вместо молчаливой пустоты. */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("UI error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ margin: 40, border: "1px solid var(--bad)", borderRadius: 10,
          padding: 20, background: "var(--surface)" }}>
          <h3 style={{ color: "var(--bad)" }}>Ошибка интерфейса — сообщите этот текст:</h3>
          <pre style={{ whiteSpace: "pre-wrap", font: "12px var(--mono)", color: "var(--dim)" }}>
            {this.state.error.message}
            {"\n\n"}
            {this.state.error.stack?.slice(0, 1500)}
          </pre>
          <button onClick={() => this.setState({ error: null })}>Попытаться продолжить</button>
        </div>
      );
    }
    return this.props.children;
  }
}
