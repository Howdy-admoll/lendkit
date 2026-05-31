"""
LendKit — Demo Data Seeder
Inserts 50 realistic loans across all lifecycle states.

Usage (with the stack running):
    pip install psycopg2-binary
    python scripts/seed_demo.py
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values

# ---------------------------------------------------------------------------
# Config — matches docker-compose defaults
# ---------------------------------------------------------------------------

LOANS_DSN       = "host=localhost port=5432 dbname=loans       user=lendkit password=lendkit"
REPAY_DSN       = "host=localhost port=5432 dbname=repayment   user=lendkit password=lendkit"
COLLECTIONS_DSN = "host=localhost port=5432 dbname=collections user=lendkit password=lendkit"

TENANT_ID = "lendkit-test"

UTC = timezone.utc
NOW = datetime.now(UTC)


def uid() -> str:
    return str(uuid.uuid4())


def rand_amount(lo: int, hi: int, step: int = 50_000_00) -> int:
    return random.randint(lo // step, hi // step) * step


def rand_date(days_ago_min: int, days_ago_max: int) -> datetime:
    return NOW - timedelta(days=random.randint(days_ago_min, days_ago_max))


FIRST_NAMES = ["Amara","Chidi","Fatima","Emeka","Ngozi","Bola","Tunde",
               "Kemi","Seun","Adaeze","Ibrahim","Yetunde","Femi","Zainab","Uche"]
LAST_NAMES  = ["Okafor","Adeyemi","Bello","Eze","Nwosu","Abubakar","Okonkwo",
               "Adeleke","Mohammed","Chukwu","Obi","Hassan","Nwachukwu","Dada","Musa"]
PURPOSES    = ["business","personal","education","medical","other"]


# ---------------------------------------------------------------------------
# Build the 50-loan plan
# (loan_state, repay_status, dpd)
# ---------------------------------------------------------------------------

PLAN: list[tuple[str, str, int]] = []
# 20 healthy active loans
for _ in range(20):
    PLAN.append(("active", "current", 0))
# 5 offer_accepted (disbursement in flight)
for _ in range(5):
    PLAN.append(("offer_accepted", "", 0))
# 5 approved (awaiting borrower)
for _ in range(5):
    PLAN.append(("approved", "", 0))
# 5 rejected
for _ in range(5):
    PLAN.append(("rejected", "", 0))
# 5 at-risk (1-7 DPD)
for _ in range(5):
    PLAN.append(("active", "at_risk", random.randint(1, 7)))
# 5 delinquent (8-89 DPD)
for _ in range(5):
    PLAN.append(("active", "delinquent", random.randint(8, 89)))
# 5 default (90+ DPD)
for _ in range(5):
    PLAN.append(("active", "default", random.randint(90, 180)))


# ---------------------------------------------------------------------------
# Seed loans DB
# ---------------------------------------------------------------------------

def seed_loans(cur) -> list[tuple]:
    """Returns list of (loan_id, loan_account_id, loan_state, repay_status, dpd, principal, tenure, apr, created_at)"""
    app_rows, offer_rows, meta = [], [], []

    for loan_state, repay_status, dpd in PLAN:
        loan_id     = uid()
        customer_id = uid()
        principal   = rand_amount(5_000_000, 50_000_000)   # ₦50k–₦500k
        tenure      = random.choice([3, 6, 9, 12])
        apr         = round(random.uniform(0.20, 0.36), 4)
        created_at  = rand_date(30, 300)

        app_rows.append((
            loan_id, customer_id, TENANT_ID,
            principal, tenure,
            random.choice(PURPOSES),
            uid(),                              # kyc_verification_id
            random.randint(500, 850),           # credit_score
            random.choice(["A","B","C"]),       # credit_tier
            random.randint(15_000_000, 80_000_000),  # monthly_income_kobo
            "employed",
            loan_state,
            None, None,                         # decline_reasons, underwriting_notes
            created_at, created_at,
        ))

        if loan_state != "rejected":
            monthly = int(principal * (apr / 12) / (1 - (1 + apr / 12) ** -tenure))
            accepted = loan_state in ("offer_accepted", "active")
            offer_rows.append((
                uid(), loan_id,
                principal, tenure, apr,
                monthly, monthly * tenure,
                "bank_transfer",
                accepted,
                created_at + timedelta(hours=1) if accepted else None,
                created_at + timedelta(days=7),
                created_at + timedelta(minutes=30),
            ))

        meta.append((loan_id, customer_id, loan_state, repay_status, dpd,
                     principal, tenure, apr, created_at))

    execute_values(cur, """
        INSERT INTO loan_applications
            (id, customer_id, tenant_id, requested_amount_kobo, tenure_months,
             purpose, kyc_verification_id, credit_score, credit_tier,
             monthly_income_kobo, employment_type, state,
             decline_reasons, underwriting_notes, created_at, updated_at)
        VALUES %s ON CONFLICT (id) DO NOTHING
    """, app_rows)

    execute_values(cur, """
        INSERT INTO loan_offers
            (id, loan_id, approved_amount_kobo, tenure_months,
             annual_percentage_rate, monthly_repayment_kobo, total_repayable_kobo,
             disbursement_method, is_accepted, accepted_at, expires_at, created_at)
        VALUES %s ON CONFLICT (loan_id) DO NOTHING
    """, offer_rows)

    print(f"  ✓ {len(app_rows)} loan applications, {len(offer_rows)} offers")
    return meta


# ---------------------------------------------------------------------------
# Seed repayment DB
# ---------------------------------------------------------------------------

def seed_repayment(cur, meta: list[tuple]):
    account_rows, installment_rows = [], []

    for loan_id, customer_id, loan_state, repay_status, dpd, principal, tenure, apr, created_at in meta:
        if loan_state != "active" or not repay_status:
            continue

        monthly      = int(principal * (apr / 12) / (1 - (1 + apr / 12) ** -tenure))
        disbursed_at = created_at + timedelta(days=2)
        start_date   = (disbursed_at + timedelta(days=1)).date()
        first_due    = (disbursed_at + timedelta(days=30)).date()
        paid_n       = max(0, random.randint(0, tenure - 1))

        # Build amortisation schedule
        balance = principal
        installments = []
        for n in range(1, tenure + 1):
            interest_due   = int(balance * apr / 12)
            principal_due  = monthly - interest_due
            closing        = max(0, balance - principal_due)
            due_date       = first_due + timedelta(days=30 * (n - 1))
            paid           = n <= paid_n
            installments.append({
                "n": n, "due": due_date, "opening": balance,
                "principal": principal_due, "interest": interest_due,
                "total": monthly, "closing": closing,
                "paid": paid,
                "paid_at": NOW - timedelta(days=random.randint(1, 5)) if paid else None,
                "paid_amount": monthly if paid else None,
            })
            balance = closing

        outstanding_principal = installments[paid_n]["opening"] if paid_n < tenure else 0
        next_due = installments[paid_n]["due"] if paid_n < tenure else None
        last_paid_at = installments[paid_n - 1]["paid_at"] if paid_n > 0 else None
        last_paid_amt = monthly if paid_n > 0 else None

        account_id = uid()

        account_rows.append((
            account_id, loan_id, customer_id, TENANT_ID,
            principal, apr, tenure, monthly,
            start_date, first_due,
            outstanding_principal,
            0,                  # accrued_interest_kobo
            0,                  # accrued_penalties_kobo
            paid_n,
            next_due,
            last_paid_at,
            last_paid_amt,
            dpd,
            disbursed_at, NOW, None,
        ))

        for inst in installments:
            installment_rows.append((
                uid(), account_id,
                inst["n"], inst["due"],
                inst["opening"], inst["principal"], inst["interest"],
                inst["total"], inst["closing"],
                inst["paid"], inst["paid_at"], inst["paid_amount"],
            ))

    execute_values(cur, """
        INSERT INTO loan_accounts
            (id, loan_id, customer_id, tenant_id,
             original_principal_kobo, annual_percentage_rate, tenure_months,
             monthly_installment_kobo, start_date, first_due_date,
             outstanding_principal_kobo, accrued_interest_kobo, accrued_penalties_kobo,
             installments_paid, next_due_date, last_payment_date, last_payment_amount_kobo,
             days_past_due,
             created_at, updated_at, settled_at)
        VALUES %s ON CONFLICT (loan_id) DO NOTHING
    """, account_rows)

    execute_values(cur, """
        INSERT INTO schedule_installments
            (id, loan_account_id, installment_number, due_date,
             opening_balance_kobo, principal_due_kobo, interest_due_kobo,
             total_due_kobo, closing_balance_kobo,
             is_paid, paid_at, paid_amount_kobo)
        VALUES %s
    """, installment_rows)

    print(f"  ✓ {len(account_rows)} loan accounts, {len(installment_rows)} installments")


# ---------------------------------------------------------------------------
# Seed collections DB
# ---------------------------------------------------------------------------

def seed_collections(cur, meta: list[tuple]):
    case_rows = []

    for loan_id, customer_id, loan_state, repay_status, dpd, *_ in meta:
        if repay_status not in ("delinquent", "default"):
            continue

        state = "OPEN" if dpd < 30 else ("AGENT_ASSIGNED" if dpd < 60 else "PROMISE_TO_PAY")
        opened_at = NOW - timedelta(days=dpd)

        case_rows.append((
            uid(), loan_id, customer_id,
            dpd, state,
            opened_at, NOW,
        ))

    execute_values(cur, """
        INSERT INTO collection_cases
            (id, loan_id, borrower_id, days_past_due, state, created_at, updated_at)
        VALUES %s ON CONFLICT (loan_id) DO NOTHING
    """, case_rows)

    print(f"  ✓ {len(case_rows)} collection cases")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Seeding LendKit demo data (50 loans)…\n")

    print("› Loans database")
    with psycopg2.connect(LOANS_DSN) as conn:
        with conn.cursor() as cur:
            meta = seed_loans(cur)
        conn.commit()

    print("› Repayment database")
    with psycopg2.connect(REPAY_DSN) as conn:
        with conn.cursor() as cur:
            seed_repayment(cur, meta)
        conn.commit()

    print("› Collections database")
    with psycopg2.connect(COLLECTIONS_DSN) as conn:
        with conn.cursor() as cur:
            seed_collections(cur, meta)
        conn.commit()

    print("\nDone! Refresh the dashboard → http://localhost:3000")


if __name__ == "__main__":
    main()
