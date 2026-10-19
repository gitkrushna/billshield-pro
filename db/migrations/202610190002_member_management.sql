-- migrate:up
-- Membership rows survive removal to preserve attribution and tenant-qualified FKs.
ALTER TABLE billshield.org_members ADD COLUMN removed_at timestamptz;
CREATE OR REPLACE FUNCTION billshield.membership_role(p_user uuid,p_org uuid) RETURNS text
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 SELECT role FROM billshield.org_members WHERE user_id=p_user AND org_id=p_org
 AND removed_at IS NULL AND p_user=billshield.current_user_id()
$$;
CREATE OR REPLACE FUNCTION billshield.in_org(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 SELECT p_org=billshield.current_org_id() AND EXISTS(SELECT 1 FROM billshield.org_members
 WHERE org_id=p_org AND user_id=billshield.current_user_id() AND removed_at IS NULL)
$$;
CREATE OR REPLACE FUNCTION billshield.create_org(p_name text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_org uuid;
 BEGIN
 IF NOT EXISTS(SELECT 1 FROM billshield.users WHERE id=billshield.current_user_id() AND verified_at IS NOT NULL) THEN
 RAISE EXCEPTION 'Verified identity required' USING ERRCODE='42501'; END IF;
 INSERT INTO billshield.orgs(name) VALUES(p_name) RETURNING id INTO v_org;
 INSERT INTO billshield.org_members(org_id,user_id,role) VALUES(v_org,billshield.current_user_id(),'owner');
 RETURN v_org;
 END $$;
CREATE OR REPLACE FUNCTION billshield.accept_invitation(p_token_hash text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_inv billshield.invitations%ROWTYPE;
 BEGIN
 SELECT i.* INTO v_inv FROM billshield.invitations i JOIN billshield.users u ON u.id=billshield.current_user_id()
 WHERE i.token_hash=p_token_hash AND i.accepted_at IS NULL AND i.expires_at>now()
 AND i.email=u.email AND u.verified_at IS NOT NULL FOR UPDATE OF i;
 IF v_inv.id IS NULL THEN RAISE EXCEPTION 'Valid invitation required' USING ERRCODE='42501'; END IF;
 INSERT INTO billshield.org_members(org_id,user_id,role) VALUES(v_inv.org_id,billshield.current_user_id(),'member')
 ON CONFLICT(org_id,user_id) DO UPDATE SET removed_at=NULL;
 UPDATE billshield.invitations SET accepted_at=now() WHERE id=v_inv.id;
 RETURN v_inv.org_id;
 END $$;
CREATE FUNCTION billshield.manage_member(p_user uuid,p_role text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_org uuid:=billshield.current_org_id(); v_current text;
 BEGIN
 -- Serialize owner-count decisions for this organisation.
 PERFORM 1 FROM billshield.orgs WHERE id=v_org FOR UPDATE;
 IF NOT coalesce(billshield.is_owner(v_org),false) THEN
 RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
 IF p_role IS NOT NULL AND p_role NOT IN ('owner','member') THEN RAISE EXCEPTION 'Invalid role'; END IF;
 SELECT role INTO v_current FROM billshield.org_members WHERE org_id=v_org AND user_id=p_user AND removed_at IS NULL;
 IF v_current IS NULL THEN RAISE EXCEPTION 'Active member required' USING ERRCODE='42501'; END IF;
 IF v_current='owner' AND p_role IS DISTINCT FROM 'owner' AND
 (SELECT count(*) FROM billshield.org_members WHERE org_id=v_org AND role='owner' AND removed_at IS NULL)<=1 THEN
 RAISE EXCEPTION 'Last owner cannot be removed or demoted' USING ERRCODE='42501'; END IF;
 UPDATE billshield.org_members SET role=coalesce(p_role,role),removed_at=CASE WHEN p_role IS NULL THEN now() ELSE NULL END
 WHERE org_id=v_org AND user_id=p_user;
 END $$;
REVOKE ALL ON FUNCTION billshield.manage_member(uuid,text) FROM PUBLIC;
-- Runtime grants are installed by provision_runtime.py after migration.

-- migrate:down
-- Forward-only: no destructive rollback.
