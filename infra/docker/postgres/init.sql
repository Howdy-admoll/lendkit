-- =============================================================================
-- LendKit PostgreSQL Initialization
-- Creates one logical database per service, grants access, adds extensions.
-- Runs automatically on first `docker compose up`.
-- =============================================================================

-- Service databases (kyc is the POSTGRES_DB default, already created)
CREATE DATABASE credit;
CREATE DATABASE loans;
CREATE DATABASE repayment;
CREATE DATABASE disbursement;
CREATE DATABASE notification;
CREATE DATABASE collections;

-- Grants
GRANT ALL PRIVILEGES ON DATABASE kyc          TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE credit       TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE loans        TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE repayment    TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE disbursement TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE notification TO lendkit;
GRANT ALL PRIVILEGES ON DATABASE collections  TO lendkit;

-- Extensions per database
\c kyc
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

\c credit
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

\c loans
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

\c repayment
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

\c disbursement
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

\c notification
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

\c collections
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
