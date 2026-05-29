import { useState, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Activity } from "lucide-react";
import { login, setToken } from "../api/client";

export default function LoginPage() {
  const navigate = useNavigate();
  const [tenantId, setTenantId] = useState("lendkit-test");
  const [apiKey, setApiKey]     = useState("test-api-key");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { access_token } = await login(tenantId, apiKey);
      setToken(access_token);
      navigate("/overview");
    } catch {
      setError("Invalid tenant ID or API key.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-8 w-full max-w-sm">
        <div className="flex items-center gap-2 mb-8">
          <Activity size={22} className="text-brand-600" />
          <span className="text-lg font-semibold text-gray-900">LendKit</span>
        </div>

        <h1 className="text-xl font-semibold text-gray-900 mb-1">Sign in</h1>
        <p className="text-sm text-gray-500 mb-6">Access the admin dashboard</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Tenant ID</label>
            <input
              type="text"
              value={tenantId}
              onChange={e => setTenantId(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
              required
            />
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-brand-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-brand-700 transition-colors disabled:opacity-60"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
