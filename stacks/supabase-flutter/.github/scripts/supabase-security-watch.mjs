#!/usr/bin/env node
import fs from "node:fs";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  console.error("usage: supabase-security-watch.mjs <advisor.json> <result.json>");
  process.exit(2);
}
const projectRef = process.env.SUPABASE_PROJECT_REF ?? "unknown";
const dashboardUrl = `https://supabase.com/dashboard/project/${projectRef}/advisors/security`;
const ignoredCacheKeys = new Set([
  // PostGIS owns this catalog table; the local RLS guard excludes it for the same reason.
  "rls_disabled_in_public_public_spatial_ref_sys",
  // GoTrue migration history, reviewed alongside backend/security/rls_disabled_allowlist.txt.
  "rls_disabled_in_public_public_schema_migrations",
]);
function unhealthy(reason) {
  fs.writeFileSync(outputPath, JSON.stringify({ status: "unhealthy", reason, dashboardUrl }, null, 2));
}
let payload;
try { payload = JSON.parse(fs.readFileSync(inputPath, "utf8")); }
catch (error) {
  unhealthy(`Advisor response was not valid JSON: ${error.message}`);
  process.exit(0);
}
if (!payload || typeof payload !== "object" || !Array.isArray(payload.lints)) {
  unhealthy("Advisor response did not contain a lints array.");
  process.exit(0);
}
const malformed = payload.lints.find((lint) =>
  !lint || typeof lint !== "object" || typeof lint.level !== "string" ||
  typeof lint.cache_key !== "string" || typeof lint.title !== "string"
);
if (malformed) {
  unhealthy("Advisor response contained a malformed lint entry.");
  process.exit(0);
}
const errors = payload.lints.filter((lint) => lint.level === "ERROR");
const actionable = errors.filter((lint) => !ignoredCacheKeys.has(lint.cache_key));
const ignored = errors.filter((lint) => ignoredCacheKeys.has(lint.cache_key));
const findings = actionable.map((lint) => ({
  cacheKey: lint.cache_key, title: lint.title,
  detail: typeof lint.detail === "string" ? lint.detail : "No detail supplied.",
  remediation: typeof lint.remediation === "string" ? lint.remediation : "",
  entity: typeof lint.metadata?.name === "string" ? lint.metadata.name : "unknown",
  schema: typeof lint.metadata?.schema === "string" ? lint.metadata.schema : "unknown",
}));
fs.writeFileSync(outputPath, JSON.stringify({
  status: findings.length ? "action_required" : "clean",
  projectRef, dashboardUrl, checkedAt: new Date().toISOString(), findings,
  ignored: ignored.map((lint) => lint.cache_key),
  totals: { all: payload.lints.length, errors: errors.length,
    actionableErrors: findings.length, ignoredErrors: ignored.length },
}, null, 2));
