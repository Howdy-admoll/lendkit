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
  borrower_id: string;
  status: LoanStatus;
  requested_amount_kobo: number;
  approved_amount_kobo?: number;
  tenure_months: number;
  annual_rate?: number;
  purpose: string;
  created_at: string;
  updated_at: string;
}

export interface LoanAccount {
  loan_id: string;
  borrower_id: string;
  principal_kobo: number;
  outstanding_kobo: number;
  dpd: number;
  dpd_status: DPDStatus;
  annual_rate: number;
  tenure_months: number;
  first_due_date: string;
  created_at: string;
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
  case_id: string;
  loan_id: string;
  borrower_id: string;
  dpd: number;
  state: string;
  agent_id?: string;
  promise_date?: string;
  created_at: string;
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
  list: () => api.get<Loan[]>("/loans/v1/applications"),
  get: (id: string) => api.get<Loan>(`/loans/v1/applications/${id}`),
};

export const repaymentApi = {
  getAccount: (loanId: string) => api.get<LoanAccount>(`/repayment/v1/loans/${loanId}`),
  getSchedule: (loanId: string) => api.get<ScheduleItem[]>(`/repayment/v1/loans/${loanId}/schedule`),
  listAccounts: () => api.get<LoanAccount[]>("/repayment/v1/loans"),
};

export const collectionsApi = {
  listCases: () => api.get<CollectionCase[]>("/collections/v1/cases"),
  getCase: (loanId: string) => api.get<CollectionCase>(`/collections/v1/cases/${loanId}`),
};

export const kycApi = {
  list: () => api.get<KYCApplication[]>("/kyc/v1/applications"),
  get: (id: string) => api.get<KYCApplication>(`/kyc/v1/applications/${id}`),
};
