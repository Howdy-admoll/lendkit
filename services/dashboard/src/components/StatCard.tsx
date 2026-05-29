import clsx from "clsx";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon: LucideIcon;
  color?: "blue" | "green" | "amber" | "red";
}

const colorMap = {
  blue:  { bg: "bg-blue-50",  icon: "text-blue-600" },
  green: { bg: "bg-green-50", icon: "text-green-600" },
  amber: { bg: "bg-amber-50", icon: "text-amber-600" },
  red:   { bg: "bg-red-50",   icon: "text-red-600" },
};

export default function StatCard({ label, value, sub, icon: Icon, color = "blue" }: StatCardProps) {
  const c = colorMap[color];
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-start gap-4">
      <div className={clsx("p-2.5 rounded-lg", c.bg)}>
        <Icon size={18} className={c.icon} />
      </div>
      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-semibold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}
