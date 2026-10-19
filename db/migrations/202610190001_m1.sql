-- migrate:up
-- Forward-only M1 schema. No destructive rollback.
CREATE SCHEMA billshield;
REVOKE ALL ON SCHEMA billshield FROM PUBLIC;
create table billshield.source_documents (
 source_key text primary key, title text not null, url text not null,
 publisher text not null, authority_level text not null,
 document_type text not null, notification_no text, issued_on date,
 edition text, licence text not null default 'unverified',
 local_file text, content_sha256 text, retrieved_at timestamptz not null default now(),
 coverage_through date, retrieval_status text not null,
 notes text
);
create table billshield.hsn_codes (
 id uuid primary key, source_key text not null references billshield.source_documents,
 code text not null check(code ~ '^[0-9]{4}([0-9]{2})?([0-9]{2})?$'),
 digits integer not null check(digits in (4,6,8)), parent_code text,
 chapter text not null check(chapter ~ '^[0-9]{2}$'), description_raw text not null,
 unit_raw text, customs_duty_raw text, source_page integer not null,
 source_edition text not null, extraction_status text not null,
 unique(source_key,code), check(length(code)=digits),
 foreign key(source_key,parent_code) references billshield.hsn_codes(source_key,code) deferrable initially deferred
);
-- Customs duty text above is deliberately NOT a GST-rate column.
create index hsn_code_prefix_idx on billshield.hsn_codes(code text_pattern_ops);

create table billshield.rate_entries (
 id uuid primary key, source_key text not null references billshield.source_documents,
 schedule text not null, entry_no text not null, hsn_selector_raw text not null,
 description_raw text not null, component text not null check(component in ('CGST','SGST','UTGST','IGST','CESS')),
 component_rate_raw text not null, component_rate_pct numeric(10,4),
 jurisdiction text not null check(jurisdiction in ('IN','IN-GA')),
 effective_from date not null, effective_to date,
 source_page integer not null, extraction_status text not null,
 currentness_status text not null, human_reviewed boolean not null default false,
 unique(source_key,schedule,entry_no),
 check(component_rate_pct is null or component_rate_pct>=0),
 check(effective_to is null or effective_to>effective_from)
);
-- No UNIQUE(hsn): multiple product descriptions, concessions and periods may apply.
create table billshield.rate_scopes (
 rate_entry_id uuid references billshield.rate_entries on delete cascade,
 scope_type text not null check(scope_type in ('global','chapter','heading','subheading','item','raw')),
 scope_code text not null, selector_status text not null,
 primary key(rate_entry_id,scope_type,scope_code)
);
create table billshield.rate_conditions (
 id uuid primary key default gen_random_uuid(), rate_entry_id uuid not null references billshield.rate_entries,
 condition_text text not null, predicate_json jsonb, required_facts text[],
 reviewed_by text, reviewed_at timestamptz
);
create table billshield.classification_rules (
 id uuid primary key, source_key text not null references billshield.source_documents,
 rule_kind text not null, scope_type text not null, scope_code text,
 rule_number text, parent_rule_id uuid references billshield.classification_rules,
 title text not null, text_original text not null, language text not null default 'en',
 source_page integer not null, applicability_status text not null,
 human_reviewed boolean not null default false, effective_from date, effective_to date, publication_date date, search_terms text not null default '',
 fts_en tsvector generated always as (
  setweight(to_tsvector('english'::regconfig,coalesce(title,'')), 'A') ||
  setweight(to_tsvector('english'::regconfig,coalesce(search_terms,'')), 'B') ||
  setweight(to_tsvector('english'::regconfig,coalesce(text_original,'')), 'C')
 ) stored,
 fts_simple tsvector generated always as (
  to_tsvector('simple'::regconfig,coalesce(title,'') || ' ' || coalesce(search_terms,'') || ' ' || coalesce(text_original,''))
 ) stored
);
create index rules_fts_en_idx on billshield.classification_rules using gin(fts_en);
create index rules_fts_simple_idx on billshield.classification_rules using gin(fts_simple);
create index rules_scope_idx on billshield.classification_rules(scope_type,scope_code);
-- Cross-references do not duplicate the authoritative chapter note.
create table billshield.rule_links (
 rule_id uuid references billshield.classification_rules on delete cascade,
 scope_type text not null, scope_code text not null, relation text not null,
 primary key(rule_id,scope_type,scope_code,relation)
);
create table billshield.search_synonyms (
 term text not null, language text not null, expansions text[] not null,
 provenance text not null, reviewed boolean not null default false,
 primary key(term,language)
);
create table billshield.rulings (
 id uuid primary key, source_key text not null references billshield.source_documents,
 applicant text not null, authority text not null, state text,
 order_no text not null, order_date date, order_date_status text not null,
 facts_original text, classification_codes text[], outcome_text text,
 rate_at_order_text text, appeal_status text not null default 'unverified',
 binding_scope text, status text check(status in ('in_force','stayed','reversed','appealed','unverified')),
 appeal_search_as_of date, reverses_ruling_id uuid references billshield.rulings,
 source_pages text, extraction_method text not null, review_status text not null,
 unique(authority,order_no)
);
create table billshield.ruling_links (
 parent_id uuid references billshield.rulings, child_id uuid references billshield.rulings,
 relationship text not null, source_key text references billshield.source_documents,
 primary key(parent_id,child_id,relationship)
);
create table billshield.data_coverage (
 scope_code text not null, corpus_type text not null, jurisdiction text not null,
 checked_on date not null, verified_through date, complete boolean not null default false,
 notes text not null, primary key(scope_code,corpus_type,jurisdiction,checked_on)
);

create table billshield.law_snapshots (
 id text primary key, created_at timestamptz not null default now(), source_keys text[] not null,
 coverage_status text not null, notes text not null, content_sha256 text not null, manifest_json jsonb not null
);

CREATE TABLE billshield.law_snapshot_members (
 snapshot_id text REFERENCES billshield.law_snapshots, kind text NOT NULL,
 record_id text NOT NULL, record_sha256 text NOT NULL,
 PRIMARY KEY(snapshot_id,kind,record_id)
);
CREATE TABLE billshield.section_chapters (chapter text PRIMARY KEY,section text NOT NULL);
CREATE TABLE billshield.boundary_map (
 left_heading text NOT NULL,right_heading text NOT NULL,notes text NOT NULL DEFAULT '',
 PRIMARY KEY(left_heading,right_heading)
);
INSERT INTO billshield.boundary_map VALUES
 ('1905','2106',''),('0402','2202',''),('1704','2106',''),('3004','3304',''),('2501','3402','');
-- Reserved for a later embedding adapter. No vector extension and no populated vectors.
CREATE TABLE billshield.ruling_embeddings (
 ruling_id uuid REFERENCES billshield.rulings,model_id text NOT NULL,
 dimensions integer CHECK(dimensions>0),embedding double precision[],
 PRIMARY KEY(ruling_id,model_id)
);

CREATE TABLE billshield.users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),email text NOT NULL,
 verified_at timestamptz NOT NULL DEFAULT now(),created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE billshield.identities (
 issuer text NOT NULL,subject text NOT NULL,user_id uuid NOT NULL REFERENCES billshield.users,
 PRIMARY KEY(issuer,subject)
);
CREATE TABLE billshield.orgs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text NOT NULL CHECK(length(trim(name))>0),
 research_opt_in boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE billshield.org_members (
 org_id uuid REFERENCES billshield.orgs,user_id uuid REFERENCES billshield.users,
 role text NOT NULL CHECK(role IN ('owner','member')),created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(org_id,user_id)
);
CREATE TABLE billshield.invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 email text NOT NULL,token_hash text NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 invited_by uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT (now()+interval '7 days'),accepted_at timestamptz,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '7 days'),
 FOREIGN KEY(org_id,invited_by) REFERENCES billshield.org_members(org_id,user_id),UNIQUE(org_id,id)
);
CREATE TABLE billshield.products (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 created_by uuid NOT NULL,name text NOT NULL,client_name text,
 facts jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(org_id,created_by) REFERENCES billshield.org_members(org_id,user_id),UNIQUE(org_id,id)
);
CREATE TABLE billshield.files (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 uploaded_by uuid NOT NULL,object_key text NOT NULL UNIQUE,declared_size bigint NOT NULL CHECK(declared_size>0 AND declared_size<=10485760),
 declared_type text NOT NULL CHECK(declared_type IN ('application/pdf','image/png','image/jpeg')),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','ready','rejected')),
 actual_size bigint CHECK(actual_size>0 AND actual_size<=10485760),actual_type text,sha256 text,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(org_id,id),
 FOREIGN KEY(org_id,uploaded_by) REFERENCES billshield.org_members(org_id,user_id),
 CHECK(status<>'ready' OR(actual_size IS NOT NULL AND actual_type IN ('application/pdf','image/png','image/jpeg') AND sha256 ~ '^[0-9a-f]{64}$'))
);
CREATE TABLE billshield.own_rulings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 declared_by uuid NOT NULL,file_id uuid,party_name text NOT NULL,facts jsonb NOT NULL DEFAULT '{}',
 effective_from date,effective_to date,status text NOT NULL DEFAULT 'unverified',
 applicability_verified boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,id),FOREIGN KEY(org_id,declared_by) REFERENCES billshield.org_members(org_id,user_id),
 FOREIGN KEY(org_id,file_id) REFERENCES billshield.files(org_id,id)
);
CREATE TABLE billshield.checks (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 user_id uuid NOT NULL,product_id uuid NOT NULL,file_id uuid,own_ruling_id uuid,
 query text NOT NULL DEFAULT '',product_facts_snapshot jsonb NOT NULL DEFAULT '{}',bill_fields jsonb,
 as_of_date date NOT NULL,jurisdiction text NOT NULL,
 result text CHECK(result IN ('Supported','Rate right, HSN wrong','Wrong','Disputable','Need more info')),
 confidence_band text CHECK(confidence_band IN ('High','Medium','Low')),next_step text,
 needs_review boolean NOT NULL DEFAULT false,exposure_json jsonb,overpayment_json jsonb,
 law_snapshot_id text REFERENCES billshield.law_snapshots,prompt_version text,model_id text,
 expected_model_version text,resolved_model_version text,issued_snapshot jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(org_id,id),
 FOREIGN KEY(org_id,user_id) REFERENCES billshield.org_members(org_id,user_id),
 FOREIGN KEY(org_id,product_id) REFERENCES billshield.products(org_id,id),
 FOREIGN KEY(org_id,file_id) REFERENCES billshield.files(org_id,id),
 FOREIGN KEY(org_id,own_ruling_id) REFERENCES billshield.own_rulings(org_id,id)
);
CREATE TABLE billshield.reports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 check_id uuid NOT NULL,snapshot jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,id),FOREIGN KEY(org_id,check_id) REFERENCES billshield.checks(org_id,id)
);
CREATE TABLE billshield.check_citations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 check_id uuid NOT NULL,source_key text NOT NULL REFERENCES billshield.source_documents,
 source_page integer,supporting_quote text NOT NULL,claim text NOT NULL,quote_verified boolean NOT NULL DEFAULT false,
 FOREIGN KEY(org_id,check_id) REFERENCES billshield.checks(org_id,id),UNIQUE(org_id,id)
);
CREATE TABLE billshield.audit_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 actor_id uuid NOT NULL,check_id uuid,event_type text NOT NULL,payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(org_id,id),
 FOREIGN KEY(org_id,actor_id) REFERENCES billshield.org_members(org_id,user_id),
 FOREIGN KEY(org_id,check_id) REFERENCES billshield.checks(org_id,id)
);
CREATE TABLE billshield.cached_analyses (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 facts_fingerprint text NOT NULL,law_snapshot_id text NOT NULL REFERENCES billshield.law_snapshots,
 as_of_date date NOT NULL,jurisdiction text NOT NULL,own_ruling_fingerprint text NOT NULL,
 model_id text NOT NULL,prompt_version text NOT NULL,policy_version text NOT NULL,
 analysis jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,facts_fingerprint,law_snapshot_id,as_of_date,jurisdiction,own_ruling_fingerprint,model_id,prompt_version,policy_version),
 UNIQUE(org_id,id)
);
CREATE TABLE billshield.report_shares (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 report_id uuid NOT NULL,created_by uuid NOT NULL,token_hash text NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT(now()+interval '7 days'),revoked_at timestamptz,
 CHECK(expires_at>created_at AND expires_at<=created_at+interval '7 days'),
 FOREIGN KEY(org_id,created_by) REFERENCES billshield.org_members(org_id,user_id),
 FOREIGN KEY(org_id,report_id) REFERENCES billshield.reports(org_id,id),UNIQUE(org_id,id)
);
CREATE TABLE billshield.jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES billshield.orgs,
 kind text NOT NULL,payload jsonb NOT NULL,status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
 run_after timestamptz NOT NULL DEFAULT now(),attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 lease_token uuid,leased_until timestamptz,last_error text,idempotency_key text,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(org_id,idempotency_key),UNIQUE(org_id,id)
);
CREATE INDEX jobs_ready ON billshield.jobs(org_id,run_after) WHERE status IN ('queued','running');

CREATE FUNCTION billshield.current_user_id() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT nullif(current_setting('app.user_id',true),'')::uuid
$$;
CREATE FUNCTION billshield.current_org_id() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT nullif(current_setting('app.org_id',true),'')::uuid
$$;
-- These narrowly scoped definer functions are the identity/bootstrap boundary.
-- Their role is trusted API middleware, which must verify JWT/email first.
CREATE FUNCTION billshield.identity_for_subject(p_issuer text,p_subject text,p_email text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_id uuid;
 BEGIN
 IF length(trim(p_issuer))=0 OR length(trim(p_subject))=0 OR p_email IS NULL OR position('@' IN p_email)=0 THEN
 RAISE EXCEPTION 'Verified identity required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_issuer||chr(1)||p_subject,0));
 SELECT user_id INTO v_id FROM billshield.identities WHERE issuer=p_issuer AND subject=p_subject;
 IF v_id IS NULL THEN
 INSERT INTO billshield.users(email) VALUES(lower(trim(p_email))) RETURNING id INTO v_id;
 INSERT INTO billshield.identities VALUES(p_issuer,p_subject,v_id);
 ELSE UPDATE billshield.users SET email=lower(trim(p_email)),verified_at=now() WHERE id=v_id;
 END IF;
 RETURN v_id;
 END $$;
CREATE FUNCTION billshield.membership_role(p_user uuid,p_org uuid) RETURNS text
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 SELECT role FROM billshield.org_members WHERE user_id=p_user AND org_id=p_org
 AND p_user=billshield.current_user_id()
$$;
CREATE FUNCTION billshield.in_org(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 SELECT p_org=billshield.current_org_id() AND EXISTS(SELECT 1 FROM billshield.org_members
 WHERE org_id=p_org AND user_id=billshield.current_user_id())
$$;
CREATE FUNCTION billshield.is_owner(p_org uuid) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 SELECT billshield.in_org(p_org) AND billshield.membership_role(billshield.current_user_id(),p_org)='owner'
$$;
CREATE FUNCTION billshield.create_org(p_name text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_org uuid;
 BEGIN
 IF NOT EXISTS(SELECT 1 FROM billshield.users WHERE id=billshield.current_user_id() AND verified_at IS NOT NULL) THEN
 RAISE EXCEPTION 'Verified identity required' USING ERRCODE='42501'; END IF;
 INSERT INTO billshield.orgs(name) VALUES(p_name) RETURNING id INTO v_org;
 INSERT INTO billshield.org_members VALUES(v_org,billshield.current_user_id(),'owner',now());
 RETURN v_org;
 END $$;
CREATE FUNCTION billshield.invite_member(p_email text,p_token_hash text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_id uuid;
 BEGIN
 IF NOT coalesce(billshield.is_owner(billshield.current_org_id()),false) THEN
 RAISE EXCEPTION 'Owner required' USING ERRCODE='42501'; END IF;
 IF p_email IS NULL OR position('@' IN p_email)=0 THEN RAISE EXCEPTION 'Invalid email'; END IF;
 INSERT INTO billshield.invitations(org_id,email,token_hash,invited_by)
 VALUES(billshield.current_org_id(),lower(trim(p_email)),p_token_hash,billshield.current_user_id()) RETURNING id INTO v_id;
 RETURN v_id;
 END $$;
CREATE FUNCTION billshield.accept_invitation(p_token_hash text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,billshield AS $$
 DECLARE v_inv billshield.invitations%ROWTYPE;
 BEGIN
 SELECT i.* INTO v_inv FROM billshield.invitations i JOIN billshield.users u ON u.id=billshield.current_user_id()
 WHERE i.token_hash=p_token_hash AND i.accepted_at IS NULL AND i.expires_at>now()
 AND i.email=u.email AND u.verified_at IS NOT NULL FOR UPDATE OF i;
 IF v_inv.id IS NULL THEN RAISE EXCEPTION 'Valid invitation required' USING ERRCODE='42501'; END IF;
 INSERT INTO billshield.org_members VALUES(v_inv.org_id,billshield.current_user_id(),'member',now()) ON CONFLICT DO NOTHING;
 UPDATE billshield.invitations SET accepted_at=now() WHERE id=v_inv.id;
 RETURN v_inv.org_id;
 END $$;
CREATE FUNCTION billshield.immutable_record() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'Issued records are immutable' USING ERRCODE='42501'; END $$;
CREATE TRIGGER reports_immutable BEFORE UPDATE OR DELETE ON billshield.reports FOR EACH ROW EXECUTE FUNCTION billshield.immutable_record();
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON billshield.audit_events FOR EACH ROW EXECUTE FUNCTION billshield.immutable_record();
CREATE FUNCTION billshield.freeze_issued_check() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN IF OLD.issued_snapshot IS NOT NULL THEN RAISE EXCEPTION 'Issued check is immutable' USING ERRCODE='42501'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF; END $$;
CREATE TRIGGER issued_check_immutable BEFORE UPDATE OR DELETE ON billshield.checks FOR EACH ROW EXECUTE FUNCTION billshield.freeze_issued_check();

-- No anonymous/public function execution or schema exposure.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA billshield FROM PUBLIC;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['users','identities','orgs','org_members','invitations','products','files','own_rulings','checks','reports','check_citations','audit_events','cached_analyses','report_shares','jobs'] LOOP
 EXECUTE format('ALTER TABLE billshield.%I ENABLE ROW LEVEL SECURITY',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['products','own_rulings','checks','check_citations','cached_analyses','jobs'] LOOP
 EXECUTE format('CREATE POLICY tenant_all ON billshield.%I USING(billshield.in_org(org_id)) WITH CHECK(billshield.in_org(org_id))',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['reports','audit_events','report_shares'] LOOP
 EXECUTE format('CREATE POLICY tenant_read ON billshield.%I FOR SELECT USING(billshield.in_org(org_id))',t);
 EXECUTE format('CREATE POLICY tenant_insert ON billshield.%I FOR INSERT WITH CHECK(billshield.in_org(org_id))',t);
 END LOOP;
END $$;
CREATE POLICY org_read ON billshield.orgs FOR SELECT USING(billshield.in_org(id));
CREATE POLICY org_owner_update ON billshield.orgs FOR UPDATE USING(billshield.is_owner(id)) WITH CHECK(billshield.is_owner(id));
CREATE POLICY membership_read ON billshield.org_members FOR SELECT USING(billshield.in_org(org_id));
CREATE POLICY invite_owner_read ON billshield.invitations FOR SELECT USING(billshield.is_owner(org_id));
CREATE POLICY files_read ON billshield.files FOR SELECT USING(billshield.in_org(org_id));
CREATE POLICY files_insert ON billshield.files FOR INSERT WITH CHECK(billshield.in_org(org_id) AND uploaded_by=billshield.current_user_id());
CREATE POLICY files_update ON billshield.files FOR UPDATE USING(billshield.in_org(org_id) AND uploaded_by=billshield.current_user_id()) WITH CHECK(billshield.in_org(org_id) AND uploaded_by=billshield.current_user_id());
CREATE POLICY share_revoke ON billshield.report_shares FOR UPDATE USING(billshield.in_org(org_id)) WITH CHECK(billshield.in_org(org_id));

-- migrate:down
-- Intentionally forward-only: restore a reviewed backup instead of destroying data.
