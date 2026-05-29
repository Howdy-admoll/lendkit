import clsx from "clsx";

type Variant = "green" | "blue" | "amber" | "red" | "gray" | "purple";

const variants: Record<Variant, string> = {
  green:  "bg-green-100 text-green-800",
  blue:   "bg-blue-100 text-blue-800",
  amber:  "bg-amber-100 text-amber-800",
  red:    "bg-red-100 text-red-800",
  gray:   "bg-gray-100 text-gray-700",
  purple: "bg-purple-100 text-purple-800",
};

export function loanStatusVariant(status: string): Variant {
  const map: Record<string, Variant> = {
    ACTIVE:         "green",
    APPROVED:       "blue",
    OFFER_SENT:     "blue",
    OFFER_ACCEPTED: "purple",
    DISBURSING:     "purple",
    UNDERWRITING:   "amber",
    DRAFT:          "gray",
    REJECTED:       "red",
    CANCELLED:      "gray",
  };
  return map[status] ?? "gray";
}

export function dpdStatusVariant(status: string): Variant {
  const map: Record<string, Variant> = {
    CURRENT:    "green",
    AT_RISK:    "amber",
    DELINQUENT: "red",
    DEFAULT:    "red",
    WRITTEN_OFF:"gray",
  };
  return map[status] ?? "gray";
}

export function collectionStateVariant(state: string): Variant {
  const map: Record<string, Variant> = {
    OPEN:           "amber",
    AGENT_ASSIGNED: "blue",
    PROMISE_TO_PAY: "purple",
    BROKEN_PROMISE: "red",
    LEGAL:          "red",
    RECOVERED:      "green",
    WRITTEN_OFF:    "gray",
  };
  return map[state] ?? "gray";
}

interface BadgeProps {
  label: string;
  variant?: Variant;
}

export default function Badge({ label, variant = "gray" }: BadgeProps) {
  return (
    <span className={clsx("inline-flex items-center px-2 py-0.5 rounded text-xs font-medium", variants[variant])}>
      {label}
    </span>
  );
}
