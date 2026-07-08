// Example Supabase Edge Function (Deno runtime).
//
// Deployed by .github/workflows/functions-deploy.yml once you set the
// SUPABASE_PROJECT_REF repo variable + SUPABASE_ACCESS_TOKEN secret. It exists so
// the deploy workflow has a real target and the layout is obvious — replace it
// with your own functions (each in its own dir under backend/supabase/functions/).
//
// Local invoke:  supabase functions serve hello
// Deployed URL:  https://<project-ref>.supabase.co/functions/v1/hello

Deno.serve((_req: Request): Response => {
  return new Response(
    JSON.stringify({ message: "Hello from {{ project_name }}" }),
    { headers: { "content-type": "application/json" } },
  );
});
