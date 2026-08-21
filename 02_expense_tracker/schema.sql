-- Expense Tracker MCP — database schema
-- Run this once against a fresh PostgreSQL database before starting the server.

CREATE TABLE IF NOT EXISTS expenses (
    id              BIGSERIAL PRIMARY KEY,
    amount          NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    category        VARCHAR(50) NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    expense_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    payment_method  VARCHAR(50) NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Speeds up the default ordering used by list_expenses / search_expenses.
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (expense_date DESC, id DESC);

-- Speeds up get_category_summary and category-filtered searches.
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category);
