// ---------------------------------------------------------------------------
// LendKit API Client
// All requests go through the API Gateway (/api prefix → proxied to :8000)
// ---------------------------------------------------------------------------

const BASE_URL = "/api";

let _token: string | null = sessionStorage.getItem("lendkit_token");

export function setToken(token: string) {
  _token = token;
  sessionStorage.setItem("lendkit_token", token);
}

export function clearToken() {
  _token = null;
  sessionStorage.removeItem("lendkit_token");
}

export function getToken() {
  return _token;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function login(tenantId: string, apiKey: string): Promise<TokenResponse> {
  const res = await fetch(`${BASE_URL}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId, api_key: apiKey, role: "admin" }),
  });
  if (!res.ok) throw new Error("Invalid credentials");
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LoanStatus =
  | "DRAFT"
  | "UNDERWRITING"
  | "APPROVED"
  | "OFFER_SENT"
  | "OFFER_ACCEPTED"
  | "DISBURSING"
  | "ACTIVE"
  | "REJECTED"
  | "CANCELLED";

export type DPDStatus = "CURRENT" | "AT_RISK" | "DELINQUENT" | "DEFAULT" | "WRITTEN_OFF";

export interface Loan {
  loan_id: string;
  customer_id: string;
  state: string;         // lowercase from API: "active", "approved", etc.
  status: string;        // alias — same as state, populated below
  requested_amount_kobo: number;
  approved_amount_kobo?: number;
  tenure_months: number;
  purpose: string;
  credit_score?: number;
  offer?: { approved_amount_kobo: number; annual_percentage_rate: number } | null;
  created_at: string;
  updated_at: string;
}

export interface LoanAccount {
  loan_id: string;
  customer_id: string;
  original_principal_kobo: number;
  outstanding_principal_kobo: number;
  days_past_due: number;
  status: DPDStatus;
  annual_percentage_rate: number;
  tenure_months: number;
  monthly_installment_kobo: number;
  installments_paid: number;
  next_due_date: string | null;
  start_date: string;
}

export interface ScheduleItem {
  installment_number: number;
  due_date: string;
  principal_kobo: number;
  interest_kobo: number;
  total_kobo: number;
  paid: boolean;
}

export interface CollectionCase {
  id: string;
  loan_id: string;
  borrower_id: string;
  days_past_due: number;
  state: string;
  assigned_agent_id?: string;
  promise_to_pay_date?: string;
  outstanding_balance_kobo: number;
  opened_at: string;
  updated_at: string;
}

export interface KYCApplication {
  id: string;
  borrower_id?: string;
  first_name: string;
  last_name: string;
  bvn: string;
  phone: string;
  email: string;
  status: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export const loansApi = {
  list: () =>
    api.get<{ items: any[]; total: number }>("/loans/api/v1/loans").then(r =>
      r.items.map((l: any) => ({
        ...l,
        loan_id: l.loan_id ?? l.id,
        status: l.state,
        approved_amount_kobo: l.offer?.approved_amount_kobo ?? l.requested_amount_kobo,
      }))
    ),
  get: (id: string) => api.get<Loan>(`/loans/api/v1/loans/${id}`),
};

export const repaymentApi = {
  getAccount: (loanId: string) => api.get<LoanAccount>(`/repayment/api/v1/repayments/${loanId}`),
  getSchedule: (loanId: string) => api.get<ScheduleItem[]>(`/repayment/api/v1/repayments/${loanId}/schedule`),
  listAccounts: () => api.get<LoanAccount[]>("/repayment/api/v1/accounts"),
};

export const collectionsApi = {
  listCases: () => api.get<CollectionCase[]>("/collections/api/v1/cases"),
  getCase: (loanId: string) => api.get<CollectionCase>(`/collections/api/v1/cases/${loanId}`),
};

export const kycApi = {
  list: () => api.get<KYCApplication[]>("/kyc/api/v1/kyc/"),
  get: (id: string) => api.get<KYCApplication>(`/kyc/api/v1/kyc/${id}`),
};
