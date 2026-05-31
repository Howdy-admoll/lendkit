import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { DollarSign, FileText, AlertTriangle, TrendingUp } from "lucide-react";
import StatCard from "../components/StatCard";
import { loansApi, repaymentApi, collectionsApi, type Loan, type LoanAccount } from "../api/client";

// ₦ formatter from kobo
const fmt = (kobo: number) =>
  `₦${(kobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;

const LOAN_STATUS_COLORS: Record<string, string> = {
  ACTIVE:         "#22c55e",
  APPROVED:       "#3b82f6",
  OFFER_SENT:     "#60a5fa",
  OFFER_ACCEPTED: "#a78bfa",
  DISBURSING:     "#8b5cf6",
  UNDERWRITING:   "#f59e0b",
  DRAFT:          "#d1d5db",
  REJECTED:       "#ef4444",
  CANCELLED:      "#9ca3af",
};

const DPD_COLORS: Record<string, string> = {
  CURRENT:    "#22c55e",
  AT_RISK:    "#f59e0b",
  DELINQUENT: "#ef4444",
  DEFAULT:    "#b91c1c",
  WRITTEN_OFF:"#6b7280",
};

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  return arr.reduce((acc, item) => {
    const k = key(item);
    (acc[k] ??= []).push(item);
    return acc;
  }, {} as Record<string, T[]>);
}

export default function OverviewPage() {
  const loans    = useQuery({ queryKey: ["loans"],    queryFn: loansApi.list });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: repaymentApi.listAccounts });
  const cases    = useQuery({ queryKey: ["cases"],    queryFn: collectionsApi.listCases });

  const loanList: Loan[]        = loans.data    ?? [];
  const accountList: LoanAccount[] = accounts.data ?? [];
  const caseList                = cases.data    ?? [];

  // Stat computations
  const totalDisbursed = loanList
    .filter(l => ["active", "disbursing", "offer_accepted", "ACTIVE", "DISBURSING", "OFFER_ACCEPTED"].includes(l.status))
    .reduce((s, l) => s + (l.approved_amount_kobo ?? l.requested_amount_kobo), 0);

  const activeLoans = loanList.filter(l => ["active", "ACTIVE"].includes(l.status)).length;
  const nplLoans    = accountList.filter(l => l.days_past_due >= 90).length;
  const nplRate     = accountList.length ? ((nplLoans / accountList.length) * 100).toFixed(1) : "0.0";

  // Pie: loans by status
  const byStatus = groupBy(loanList, l => (l.status ?? "UNKNOWN").toUpperCase());
  const statusPie = Object.entries(byStatus).map(([name, items]) => ({
    name,
    value: items.length,
    fill: LOAN_STATUS_COLORS[name] ?? "#9ca3af",
  }));

  // Bar: DPD distribution
  const byDPD = groupBy(accountList, a => (a.status ?? "CURRENT").toUpperCase());
  const dpdBar = ["CURRENT", "AT_RISK", "DELINQUENT", "DEFAULT", "WRITTEN_OFF"].map(s => ({
    status: s,
    count: byDPD[s]?.length ?? 0,
    fill: DPD_COLORS[s],
  }));

  if (loans.isLoading) return <PageShell><div className="p-8 text-sm text-gray-400">Loading…</div></PageShell>;

  return (
    <PageShell>
      {/* Stats row */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Disbursed"  value={fmt(totalDisbursed)} icon={DollarSign} color="blue" />
        <StatCard label="Active Loans"     value={activeLoans}         icon={FileText}   color="green" />
        <StatCard label="NPL Rate"         value={`${nplRate}%`}       sub="90+ DPD"     icon={TrendingUp} color={parseFloat(nplRate) > 5 ? "red" : "green"} />
        <StatCard label="Open Cases"       value={caseList.length}     icon={AlertTriangle} color="amber" />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Pie: loan status */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-800 mb-4">Loans by Status</h3>
          {loanList.length === 0 ? (
            <p className="text-xs text-gray-400 py-8 text-center">No loan data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={statusPie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`} labelLine={false} fontSize={11}>
                  {statusPie.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                </Pie>
                <Legend iconSize={10} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => [`${v} loans`]} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Bar: DPD distribution */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-800 mb-4">DPD Distribution</h3>
          {accountList.length === 0 ? (
            <p className="text-xs text-gray-400 py-8 text-center">No repayment data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={dpdBar} barSize={32}>
                <XAxis dataKey="status" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
                <Tooltip formatter={(v) => [`${v} accounts`]} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {dpdBar.map((entry, i) => <Cell key={i} fill={entry.fill} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">Portfolio Overview</h1>
        <p className="text-sm text-gray-500 mt-0.5">Live snapshot across all active loans</p>
      </div>
      {children}
    </div>
  );
}
