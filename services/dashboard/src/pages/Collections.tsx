import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { collectionsApi, type CollectionCase } from "../api/client";
import Badge, { collectionStateVariant, dpdStatusVariant } from "../components/Badge";
import EmptyState from "../components/EmptyState";
import { format } from "date-fns";

function dpdLabel(dpd: number): string {
  if (dpd === 0) return "CURRENT";
  if (dpd <= 7)  return "AT_RISK";
  if (dpd <= 89) return "DELINQUENT";
  return "DEFAULT";
}

export default function CollectionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["cases"],
    queryFn: collectionsApi.listCases,
  });

  const cases: CollectionCase[] = (data ?? []).sort((a, b) => b.days_past_due - a.days_past_due);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Collections Queue</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Overdue accounts ranked by days past due — highest risk first
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-sm text-center text-gray-400">Loading…</div>
        ) : cases.length === 0 ? (
          <EmptyState
            icon={AlertTriangle}
            title="No collection cases"
            description="All loans are current — nothing in the collections queue."
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Case ID</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Loan ID</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Borrower</th>
                <th className="text-right text-xs font-medium text-gray-500 px-4 py-3">DPD</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Risk</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">State</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Promise Date</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Opened</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c, i) => (
                <tr key={c.id} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/50"}>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{c.id.slice(0, 8)}…</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{c.loan_id.slice(0, 8)}…</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{c.borrower_id.slice(0, 8)}…</td>
                  <td className="px-4 py-3 text-right font-semibold">{c.days_past_due}</td>
                  <td className="px-4 py-3">
                    <Badge label={dpdLabel(c.days_past_due)} variant={dpdStatusVariant(dpdLabel(c.days_past_due))} />
                  </td>
                  <td className="px-4 py-3">
                    <Badge label={c.state} variant={collectionStateVariant(c.state)} />
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {c.promise_to_pay_date ? format(new Date(c.promise_to_pay_date), "dd MMM yyyy") : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {format(new Date(c.opened_at), "dd MMM yyyy")}
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
