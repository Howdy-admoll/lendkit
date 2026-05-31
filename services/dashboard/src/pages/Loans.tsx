import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, FileText } from "lucide-react";
import { loansApi, type Loan } from "../api/client";
import Badge, { loanStatusVariant } from "../components/Badge";
import EmptyState from "../components/EmptyState";
import { format } from "date-fns";

const fmt = (kobo: number) =>
  `₦${(kobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;

const ALL_STATUSES = [
  "ALL", "active", "approved", "offer_accepted", "disbursing", "rejected", "cancelled",
];

export default function LoansPage() {
  const [search, setSearch]   = useState("");
  const [status, setStatus]   = useState("ALL");
  const { data, isLoading }   = useQuery({ queryKey: ["loans"], queryFn: loansApi.list });

  const loans: Loan[] = data ?? [];

  const filtered = loans.filter(l => {
    const matchStatus = status === "ALL" || (l.state ?? "") === status;
    const q = search.toLowerCase();
    const id = (l.loan_id ?? (l as any).id ?? "").toLowerCase();
    const matchSearch = !q ||
      id.includes(q) ||
      (l.customer_id ?? "").toLowerCase().includes(q) ||
      (l.purpose ?? "").toLowerCase().includes(q);
    return matchStatus && matchSearch;
  });

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Loan Pipeline</h1>
        <p className="text-sm text-gray-500 mt-0.5">All loan applications across every stage</p>
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by ID, customer, purpose…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-64"
          />
        </div>
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-500 bg-white capitalize"
        >
          {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="ml-auto text-xs text-gray-400 self-center">
          {filtered.length} of {loans.length} loans
        </span>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-center text-gray-400">Loading…</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={FileText} title="No loans found" description="Try adjusting your filters." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Loan ID</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Customer</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Status</th>
                <th className="text-right text-xs font-medium text-gray-500 px-4 py-3">Amount</th>
                <th className="text-right text-xs font-medium text-gray-500 px-4 py-3">Tenure</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Purpose</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((loan, i) => {
                const loanId = (loan.loan_id ?? (loan as any).id ?? "");
                const customerId = loan.customer_id ?? "";
                const state = loan.state ?? "";
                return (
                <tr key={loanId || i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{loanId.slice(0, 8)}…</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{customerId.slice(0, 8)}…</td>
                  <td className="px-4 py-3">
                    <Badge label={state} variant={loanStatusVariant(state.toUpperCase())} />
                  </td>
                  <td className="px-4 py-3 text-right font-medium">
                    {fmt(loan.approved_amount_kobo ?? loan.requested_amount_kobo ?? 0)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">{loan.tenure_months}mo</td>
                  <td className="px-4 py-3 text-gray-600 capitalize">{(loan.purpose ?? "").replace(/_/g, " ")}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {loan.created_at ? format(new Date(loan.created_at), "dd MMM yyyy") : "—"}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
