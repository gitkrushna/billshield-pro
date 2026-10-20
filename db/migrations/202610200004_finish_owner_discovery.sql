-- migrate:up
-- Bootstrap can discover only the caller's active ownership, before org scope.
-- Tenant data access continues to require Postgres.tenant and app.org_id.
CREATE POLICY self_owner_discovery ON billshield.org_members FOR SELECT
USING (user_id=billshield.current_user_id() AND role='owner' AND removed_at IS NULL);

-- migrate:down
-- Forward-only: no destructive rollback.
