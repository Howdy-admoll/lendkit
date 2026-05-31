import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Component, type ReactNode } from "react";
import { getToken } from "./api/client";
import Layout from "./components/Layout";
import LoginPage from "./pages/Login";
import OverviewPage from "./pages/Overview";
import LoansPage from "./pages/Loans";
import CollectionsPage from "./pages/Collections";
import BorrowersPage from "./pages/Borrowers";

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32, fontFamily: "monospace", color: "red" }}>
          <h2>App crashed</h2>
          <pre>{String(this.state.error)}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="loans" element={<LoansPage />} />
          <Route path="collections" element={<CollectionsPage />} />
          <Route path="borrowers" element={<BorrowersPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
