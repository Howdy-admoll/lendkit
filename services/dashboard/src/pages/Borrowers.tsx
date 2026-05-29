import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Users } from "lucide-react";
import { kycApi, type KYCApplication } from "../api/client";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import { format } from "date-fns";

function kycVariant(status: string) {
  const map: Record<string, "green" | "amber" | "red" | "gray"> = {
    verified: "green",
    approved: "green",
    pending:  "amber",
    review:   "amber",
    rejected: "red",
    failed:   "red",
  };
  return map[status.toLowerCase()] ?? "gray";
}

export default function BorrowersPage() {
  const [search, setSearch] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["kyc"], queryFn: kycApi.list });

  const borrowers: KYCApplication[] = data ?? [];

  const filtered = borrowers.filter(b => {
    const q = search.toLowerCase();
    return (
      !q ||
      b.first_name.toLowerCase().includes(q) ||
      b.last_name.toLowerCase().includes(q) ||
      b.email.toLowerCase().includes(q) ||
      b.bvn.includes(q) ||
      b.phone.includes(q)
    );
  });

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Borrower Profiles</h1>
        <p className="text-sm text-gray-500 mt-0.5">KYC status and identity records for all applicants</p>
      </div>

      {/* Search */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by name, email, BVN, phone…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 w-72"
          />
        </div>
        <span className="ml-auto text-xs text-gray-400 self-center">
          {filtered.length} of {borrowers.length} borrowers
        </span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-center text-gray-400">Loading…</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={Users} title="No borrowers found" description="Try adjusting your search." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Name</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Email</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Phone</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">BVN</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">KYC Status</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Applied</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((b, i) => (
                <tr key={b.id} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {b.first_name} {b.last_name}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{b.email}</td>
                  <td className="px-4 py-3 text-gray-600">{b.phone}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">
                    {b.bvn.slice(0, 4)}•••{b.bvn.slice(-4)}
                  </td>
                  <td className="px-4 py-3">
                    <Badge label={b.status} variant={kycVariant(b.status)} />
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {format(new Date(b.created_at), "dd MMM yyyy")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
