-- CloudBase computes lightweight bodies directly from public.notices. Use its SELECT policy.
ALTER FUNCTION public.class_notices_meta() SECURITY INVOKER;
NOTIFY pgrst, 'reload schema';
