-- Execute once in pgAdmin Query Tool for database moneyflow.
-- Safe view: no password hashes, session tokens or reset tokens.
CREATE OR REPLACE VIEW public.v_users_overview AS
SELECT id, username, email, phone, address, role, active, opening_balance, created_at
FROM public.users;

-- Show the simpler account overview:
SELECT * FROM public.v_users_overview ORDER BY id;
