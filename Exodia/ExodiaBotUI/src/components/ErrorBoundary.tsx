import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Renderer error:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif', color: '#e8eaed', background: '#1a1d23', minHeight: '100vh' }}>
          <h1 style={{ fontSize: 18, marginTop: 0 }}>Exodia failed to start</h1>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#f87171' }}>{this.state.error.message}</pre>
          {!window.exodia && (
            <p style={{ color: '#9aa0a9' }}>
              Preload bridge missing — restart with <code>npm run dev</code> from the{' '}
              <code>ExodiaBotUI/</code> folder.
            </p>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
