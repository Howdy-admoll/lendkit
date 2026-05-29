import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./api/client";
import Layout from "./components/Layout";
import LoginPage from "./pages/Login";
import OverviewPage from "./pages/Overview";
import LoansPage from "./pages/Loans";
import CollectionsPage from "./pages/Collections";
import BorrowersPage from "./pages/Borrowers";

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
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
  );
}
