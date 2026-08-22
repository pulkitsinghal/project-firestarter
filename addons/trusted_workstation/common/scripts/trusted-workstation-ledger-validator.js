/* Strict, read-only ledger validator for Windows Script Host and macOS JXA. */
/* ES5 syntax is intentional: Windows ships the older JScript engine. */
var MAX_BYTES = 65536;
var EXPECTED_REPO = null;

function fail(message) { throw new Error("BLOCKED " + message); }
function hasOwn(value, key) { return Object.prototype.hasOwnProperty.call(value, key); }
function rejectUnknown(value, allowed, where) {
  var allowedMap = {}, key, i;
  for (i = 0; i < allowed.length; i += 1) { allowedMap["$" + allowed[i]] = true; }
  for (key in value) {
    if (hasOwn(value, key) && !allowedMap["$" + key]) { fail(where + " has an unknown field"); }
  }
}
function requireFields(value, required, where) {
  var i;
  for (i = 0; i < required.length; i += 1) {
    if (!hasOwn(value, required[i])) { fail(where + " is missing required field: " + required[i]); }
  }
}
function isObject(value) { return value !== null && typeof value === "object" && !(value instanceof Array); }
function safeString(value, field, max) {
  if (typeof value !== "string" || value.length < 1 || value.length > max) { fail(field + " must be a bounded string"); }
  var i, code;
  for (i = 0; i < value.length; i += 1) {
    code = value.charCodeAt(i);
    if (code < 32 || (code >= 127 && code <= 159)) { fail(field + " contains terminal control characters"); }
  }
  return value;
}

function parseStrict(text) {
  var at = 0;
  function white() { while (at < text.length && /[\x20\x09\x0a\x0d]/.test(text.charAt(at))) { at += 1; } }
  function string() {
    var out = "", ch, hex, code;
    if (text.charAt(at) !== '"') { fail("invalid JSON string"); }
    at += 1;
    while (at < text.length) {
      ch = text.charAt(at); at += 1;
      if (ch === '"') { return out; }
      if (ch === "\\") {
        if (at >= text.length) { fail("invalid JSON escape"); }
        ch = text.charAt(at); at += 1;
        if (ch === '"' || ch === "\\" || ch === "/") { out += ch; }
        else if (ch === "b") { out += "\b"; }
        else if (ch === "f") { out += "\f"; }
        else if (ch === "n") { out += "\n"; }
        else if (ch === "r") { out += "\r"; }
        else if (ch === "t") { out += "\t"; }
        else if (ch === "u") {
          hex = text.substr(at, 4);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) { fail("invalid JSON unicode escape"); }
          code = parseInt(hex, 16); at += 4;
          if (code >= 0xD800 && code <= 0xDBFF) {
            if (text.substr(at, 2) !== "\\u" || !/^[0-9a-fA-F]{4}$/.test(text.substr(at + 2, 4))) { fail("unpaired JSON surrogate"); }
            var low = parseInt(text.substr(at + 2, 4), 16);
            if (low < 0xDC00 || low > 0xDFFF) { fail("unpaired JSON surrogate"); }
            out += String.fromCharCode(code, low); at += 6;
          } else if (code >= 0xDC00 && code <= 0xDFFF) { fail("unpaired JSON surrogate"); }
          else { out += String.fromCharCode(code); }
        } else { fail("invalid JSON escape"); }
      } else {
        if (ch.charCodeAt(0) < 32) { fail("unescaped JSON control character"); }
        out += ch;
      }
    }
    fail("unterminated JSON string");
  }
  function number() {
    var rest = text.substring(at), match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(rest);
    if (!match) { fail("invalid JSON number"); }
    at += match[0].length;
    var value = Number(match[0]);
    if (!isFinite(value)) { fail("non-finite JSON number"); }
    return value;
  }
  function value() {
    white();
    var ch = text.charAt(at), result, key, seen;
    if (ch === '"') { return string(); }
    if (ch === "{") {
      result = {}; seen = {}; at += 1; white();
      if (text.charAt(at) === "}") { at += 1; return result; }
      while (true) {
        white(); key = string();
        if (seen["$" + key]) { fail("duplicate JSON key"); }
        seen["$" + key] = true; white();
        if (text.charAt(at) !== ":") { fail("invalid JSON object"); }
        at += 1; result[key] = value(); white(); ch = text.charAt(at); at += 1;
        if (ch === "}") { return result; }
        if (ch !== ",") { fail("invalid JSON object"); }
      }
    }
    if (ch === "[") {
      result = []; at += 1; white();
      if (text.charAt(at) === "]") { at += 1; return result; }
      while (true) {
        result.push(value()); white(); ch = text.charAt(at); at += 1;
        if (ch === "]") { return result; }
        if (ch !== ",") { fail("invalid JSON array"); }
      }
    }
    if (text.substr(at, 4) === "true") { at += 4; return true; }
    if (text.substr(at, 5) === "false") { at += 5; return false; }
    if (text.substr(at, 4) === "null") { at += 4; return null; }
    return number();
  }
  var parsed = value(); white();
  if (at !== text.length) { fail("trailing data after JSON value"); }
  return parsed;
}

function validate(data) {
  var states = { discovered: 1, cloned: 1, unlocked: 1, verified: 1, enrolled: 1, "sync-enabled": 1, blocked: 1 };
  var checkNames = ["cloneOwned", "remoteMatch", "hooksInstalled", "canaryCiphertext", "canaryPlaintext"];
  var i, key;
  safeString(EXPECTED_REPO, "expected repository", 200);
  if (!isObject(data)) { fail("ledger must be an object"); }
  rejectUnknown(data, ["schemaVersion", "repository", "clonePath", "state", "machine", "revision", "keyFingerprint", "checks", "mutagen", "updatedAt"], "ledger");
  requireFields(data, ["schemaVersion", "repository", "clonePath", "state", "checks", "updatedAt"], "ledger");
  if (data.schemaVersion !== "1.0") { fail("unsupported schemaVersion"); }
  if (safeString(data.repository, "repository", 200) !== EXPECTED_REPO) { fail("repository does not match this project"); }
  safeString(data.clonePath, "clonePath", 1024);
  if (typeof data.state !== "string" || !states[data.state]) { fail("invalid state"); }
  safeString(data.updatedAt, "updatedAt", 64);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(data.updatedAt)) { fail("updatedAt must be a UTC RFC3339 timestamp"); }
  if (!isObject(data.checks)) { fail("checks must be an object"); }
  rejectUnknown(data.checks, checkNames, "checks");
  for (key in data.checks) {
    if (hasOwn(data.checks, key) && data.checks[key] !== "pass" && data.checks[key] !== "fail" && data.checks[key] !== "not-run") { fail("check values must be pass, fail, or not-run"); }
  }
  function requirePass(names, state) {
    for (var j = 0; j < names.length; j += 1) {
      if (data.checks[names[j]] !== "pass") { fail(state + " requires passing check: " + names[j]); }
    }
  }
  if (data.state === "cloned") { requirePass(["cloneOwned", "remoteMatch"], data.state); }
  if (data.state === "unlocked") { requirePass(["cloneOwned", "remoteMatch", "canaryCiphertext", "canaryPlaintext"], data.state); }
  if (data.state === "verified" || data.state === "enrolled" || data.state === "sync-enabled") { requirePass(checkNames, data.state); }
  if (data.state === "unlocked" || data.state === "verified" || data.state === "enrolled" || data.state === "sync-enabled") {
    if (typeof data.keyFingerprint !== "string" || !/^[0-9a-f]{64}$/.test(data.keyFingerprint)) { fail(data.state + " requires a SHA-256 key fingerprint"); }
  }
  if (hasOwn(data, "keyFingerprint") && (typeof data.keyFingerprint !== "string" || !/^[0-9a-f]{64}$/.test(data.keyFingerprint))) { fail("invalid keyFingerprint"); }
  if (hasOwn(data, "revision") && (typeof data.revision !== "string" || !/^[0-9a-f]{40}$/.test(data.revision))) { fail("invalid revision"); }
  if (hasOwn(data, "machine")) {
    if (!isObject(data.machine)) { fail("machine must be an object"); }
    rejectUnknown(data.machine, ["platform", "tailscaleNodeId", "tailscaleDnsName"], "machine");
    if (hasOwn(data.machine, "platform") && data.machine.platform !== "windows" && data.machine.platform !== "macos") { fail("invalid machine platform"); }
    if (hasOwn(data.machine, "tailscaleNodeId")) { safeString(data.machine.tailscaleNodeId, "tailscaleNodeId", 128); }
    if (hasOwn(data.machine, "tailscaleDnsName")) { safeString(data.machine.tailscaleDnsName, "tailscaleDnsName", 253); }
  }
  if (data.state === "verified" || data.state === "enrolled" || data.state === "sync-enabled") {
    if (typeof data.revision !== "string" || !/^[0-9a-f]{40}$/.test(data.revision)) { fail(data.state + " requires a full Git revision"); }
    if (!isObject(data.machine)) { fail(data.state + " requires machine evidence"); }
    requireFields(data.machine, ["platform", "tailscaleNodeId", "tailscaleDnsName"], "machine");
    if (data.machine.platform !== "windows" && data.machine.platform !== "macos") { fail("invalid machine platform"); }
    safeString(data.machine.tailscaleNodeId, "tailscaleNodeId", 128);
    safeString(data.machine.tailscaleDnsName, "tailscaleDnsName", 253);
  }
  if (hasOwn(data, "mutagen")) {
    if (!isObject(data.mutagen)) { fail("mutagen must be an object"); }
    rejectUnknown(data.mutagen, ["enabled", "sessionName", "mode", "exclusions"], "mutagen");
    requireFields(data.mutagen, ["enabled"], "mutagen");
    if (typeof data.mutagen.enabled !== "boolean") { fail("mutagen.enabled must be boolean"); }
    if (hasOwn(data.mutagen, "sessionName")) { safeString(data.mutagen.sessionName, "mutagen.sessionName", 128); }
    if (hasOwn(data.mutagen, "mode") && data.mutagen.mode !== "one-way-safe") { fail("invalid Mutagen mode"); }
    if (hasOwn(data.mutagen, "exclusions")) {
      if (!(data.mutagen.exclusions instanceof Array)) { fail("mutagen.exclusions must be an array"); }
      var seenExclusions = {};
      for (i = 0; i < data.mutagen.exclusions.length; i += 1) {
        key = safeString(data.mutagen.exclusions[i], "mutagen exclusion", 128);
        if (seenExclusions["$" + key]) { fail("duplicate Mutagen exclusion"); }
        seenExclusions["$" + key] = true;
      }
    }
  }
  if (data.state === "sync-enabled") {
    if (!isObject(data.mutagen) || data.mutagen.enabled !== true) { fail("sync-enabled requires enabled Mutagen evidence"); }
    requireFields(data.mutagen, ["sessionName", "mode", "exclusions"], "mutagen");
    safeString(data.mutagen.sessionName, "mutagen.sessionName", 128);
    if (data.mutagen.mode !== "one-way-safe") { fail("sync-enabled requires one-way-safe mode"); }
    var requiredExclusions = [".git", ".git/**", ".git-crypt/**", "*.key", "*.git-crypt.key"];
    for (i = 0; i < requiredExclusions.length; i += 1) {
      var found = false;
      for (var j = 0; j < data.mutagen.exclusions.length; j += 1) {
        if (data.mutagen.exclusions[j] === requiredExclusions[i]) { found = true; }
      }
      if (!found) { fail("sync-enabled is missing mandatory exclusion: " + requiredExclusions[i]); }
    }
  }
  return "VALID repository=" + data.repository + " state=" + data.state + " schemaVersion=1.0";
}

function readWindows(path) {
  var stream = new ActiveXObject("ADODB.Stream");
  stream.Type = 2; stream.Charset = "utf-8"; stream.Open(); stream.LoadFromFile(path);
  if (stream.Size > MAX_BYTES) { stream.Close(); fail("ledger exceeds 65536 bytes"); }
  var text = stream.ReadText(-1); stream.Close();
  if (text.charCodeAt(0) === 0xFEFF) { text = text.substring(1); }
  return text;
}
function windowsMain() {
  if (WScript.Arguments.length !== 2) { fail("usage: validator <ledger> <expected-repository>"); }
  EXPECTED_REPO = String(WScript.Arguments.Item(1));
  WScript.Echo(validate(parseStrict(readWindows(String(WScript.Arguments.Item(0))))));
}
function run(argv) {
  if (argv.length !== 2) { fail("usage: validator <ledger> <expected-repository>"); }
  EXPECTED_REPO = String(argv[1]);
  ObjC["import"]("Foundation");
  var manager = $.NSFileManager.defaultManager;
  var attrs = manager.attributesOfItemAtPathError(String(argv[0]), null);
  if (!attrs || Number(attrs.objectForKey($.NSFileSize)) > MAX_BYTES) { fail("ledger is unavailable or exceeds 65536 bytes"); }
  var text = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(String(argv[0]), $.NSUTF8StringEncoding, null));
  return validate(parseStrict(text));
}
if (typeof WScript !== "undefined") {
  try { windowsMain(); } catch (error) { WScript.StdErr.WriteLine(String(error.message || error)); WScript.Quit(1); }
}
