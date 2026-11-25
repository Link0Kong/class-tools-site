-- Only an exact, explicitly submitted query is resolved. No nickname list is returned.
BEGIN;
CREATE TABLE IF NOT EXISTS private.roster_search_keys (
  source_key text NOT NULL,
  sid text NOT NULL REFERENCES private.class_ids(sid) ON DELETE CASCADE,
  name_hash bytea NOT NULL,
  refreshed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_key, sid, name_hash)
);
CREATE INDEX IF NOT EXISTS roster_search_hash ON private.roster_search_keys (name_hash);
REVOKE ALL ON private.roster_search_keys FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.class_roster_search(p_query text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT CASE WHEN public.auth_ok() IS TRUE AND char_length(btrim(p_query)) BETWEEN 1 AND 128
    THEN coalesce((
      SELECT jsonb_agg(m.seat ORDER BY m.seat)
      FROM private.class_ids m
      WHERE m.is_test IS NOT TRUE AND (EXISTS (
        SELECT 1 FROM private.roster_search_keys k WHERE k.sid = m.sid
          AND k.refreshed_at > now() - interval '24 hours'
          AND k.name_hash = sha256(convert_to(normalize(btrim(p_query), NFC), 'UTF8'))
      ) OR EXISTS (
        -- The optional author name on a published class assignment is already visible to the class.
        SELECT 1 FROM public.homework h WHERE h.owner = m.sid AND h.archived IS NOT TRUE
          AND normalize(btrim(h.author), NFC) COLLATE "C" = normalize(btrim(p_query), NFC) COLLATE "C"
      ))
    ), '[]'::jsonb)
    ELSE '[]'::jsonb END
$fn$;
REVOKE ALL ON FUNCTION public.class_roster_search(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.class_roster_search(text) TO anon;
NOTIFY pgrst, 'reload schema';
COMMIT;
