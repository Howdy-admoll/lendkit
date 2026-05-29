import { Outlet, NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  AlertTriangle,
  Users,
  LogOut,
  Activity,
} from "lucide-react";
import { clearToken } from "../api/client";
import clsx from "clsx";

const NAV = [
  { to: "/overview",    label: "Overview",    icon: LayoutDashboard },
  { to: "/loans",       label: "Loans",       icon: FileText },
  { to: "/collections", label: "Collections", icon: AlertTriangle },
  { to: "/borrowers",   label: "Borrowers",   icon: Users },
];

export default function Layout() {
  const navigate = useNavigate();

  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-56 flex flex-col bg-white border-r border-gray-200">
        {/* Logo */}
        <div className="flex items-center gap-2 px-5 py-5 border-b border-gray-100">
          <Activity size={20} className="text-brand-600" />
          <span className="font-semibold text-gray-900 tracking-tight">LendKit</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-50 text-brand-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Logout */}
        <div className="px-3 py-4 border-t border-gray-100">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2 w-full rounded-lg text-sm font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-900 transition-colors"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
