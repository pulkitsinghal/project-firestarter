#!/bin/sh
# Keep accidental issue-closing directives out of commits and PR metadata.
# Diagnostics are deliberately content-free: commit text, refs, paths, and
# repository names must not be copied into logs.

set -eu

usage() {
    printf '%s\n' 'closing-keyword guard: invalid invocation.' >&2
    exit 2
}

reject_forbidden() {
    kind="$1"
    printf '%s\n' "closing-keyword guard: rejected ${kind}; automatic-closing directives are not allowed here." >&2
    return 1
}

contains_closing_directive() {
    awk '
        function unwrap(value, first) {
            while (length(value) > 0) {
                first = substr(value, 1, 1)
                if (index(" []({<`*_~", first) == 0) {
                    break
                }
                value = substr(value, 2)
            }
            return value
        }

        function hazardous(line, rest, tail) {
            rest = tolower(line)
            while (match(rest, /(^|[^A-Za-z0-9_])(close[sd]?|fix(es|ed)?|resolve[sd]?)([[:space:]]*:[[:space:]]*|[[:space:]]+)/)) {
                tail = unwrap(substr(rest, RSTART + RLENGTH))
                if (tail ~ /^(#[0-9]+|[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+#[0-9]+)/) {
                    return 1
                }
                if (tail ~ /^https?:\/\/[^[:space:]\/]+\/[^[:space:]\/]+\/[^[:space:]\/]+\/issues\/[0-9]+/) {
                    return 1
                }
                rest = substr(rest, RSTART + RLENGTH)
            }
            return 0
        }

        { sub(/\r$/, "") }
        hazardous($0) { found = 1 }
        END { exit found ? 0 : 1 }
    ' "$1" >/dev/null 2>&1
}

check_forbidden_file() {
    file="$1"
    kind="$2"
    if contains_closing_directive "$file"; then
        scan_status=0
    else
        scan_status=$?
    fi
    case "$scan_status" in
        0) reject_forbidden "$kind" ;;
        1) return 0 ;;
        *)
            printf '%s\n' "closing-keyword guard: ${kind} scan unavailable." >&2
            return 2
            ;;
    esac
}

reject_pr_body() {
    printf '%s\n' 'closing-keyword guard: rejected pull request body; use one canonical final Issue closure section.' >&2
    return 1
}

pr_body_scan_unavailable() {
    printf '%s\n' 'closing-keyword guard: pull request body scan unavailable.' >&2
    return 2
}

finish_pr_body_scan() {
    scan_status="$1"
    case "$scan_status" in
        0) return 0 ;;
        1) reject_pr_body ;;
        *) pr_body_scan_unavailable ;;
    esac
}

run_pr_body_scan() {
    file="$1"
    if awk '
        function unwrap(value, first) {
            while (length(value) > 0) {
                first = substr(value, 1, 1)
                if (index(" []({<`*_~", first) == 0) {
                    break
                }
                value = substr(value, 2)
            }
            return value
        }

        function hazardous(line, rest, tail) {
            rest = tolower(line)
            while (match(rest, /(^|[^A-Za-z0-9_])(close[sd]?|fix(es|ed)?|resolve[sd]?)([[:space:]]*:[[:space:]]*|[[:space:]]+)/)) {
                tail = unwrap(substr(rest, RSTART + RLENGTH))
                if (tail ~ /^(#[0-9]+|[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+#[0-9]+)/) {
                    return 1
                }
                if (tail ~ /^https?:\/\/[^[:space:]\/]+\/[^[:space:]\/]+\/[^[:space:]\/]+\/issues\/[0-9]+/) {
                    return 1
                }
                rest = substr(rest, RSTART + RLENGTH)
            }
            return 0
        }

        function valid_target(target, hash, repository_ref, slash, owner, repository) {
            if (target ~ /^#[1-9][0-9]*$/) {
                return 1
            }
            if (target !~ /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+#[1-9][0-9]*$/) {
                return 0
            }
            hash = index(target, "#")
            repository_ref = substr(target, 1, hash - 1)
            slash = index(repository_ref, "/")
            owner = substr(repository_ref, 1, slash - 1)
            repository = substr(repository_ref, slash + 1)
            if (length(owner) > 39 || owner !~ /^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$/) {
                return 0
            }
            if (owner ~ /--/ || length(repository) > 100 || repository == "." || repository == "..") {
                return 0
            }
            return repository ~ /^[A-Za-z0-9_.-]+$/
        }

        {
            sub(/\r$/, "")
            lines[++count] = $0
        }

        END {
            last = count
            while (last > 0 && lines[last] == "") {
                last--
            }

            headings = 0
            heading = 0
            for (i = 1; i <= last; i++) {
                if (lines[i] == "## Issue closure") {
                    headings++
                    heading = i
                }
            }
            if (headings != 1 || heading == 0) {
                exit 1
            }
            if (heading > 1 && lines[heading - 1] != "") {
                exit 1
            }
            if (heading + 2 > last || lines[heading + 1] != "") {
                exit 1
            }

            for (i = 1; i < heading; i++) {
                if (hazardous(lines[i])) {
                    exit 1
                }
            }

            first = heading + 2
            if (first == last && lines[first] == "None") {
                exit 0
            }

            delete seen
            for (i = first; i <= last; i++) {
                if (lines[i] !~ /^Closes: /) {
                    exit 1
                }
                target = lines[i]
                sub(/^Closes: /, "", target)
                if (!valid_target(target)) {
                    exit 1
                }
                target = tolower(target)
                if (seen[target]++) {
                    exit 1
                }
            }
            exit 0
        }
    ' "$file" >/dev/null 2>&1; then
        scan_status=0
    else
        scan_status=$?
    fi
    finish_pr_body_scan "$scan_status"
}

check_pr_body() {
    run_pr_body_scan "$1"
}

commit_file=''
title_file=''
body_file=''
commit_range=''

while [ "$#" -gt 0 ]; do
    case "$1" in
        --commit-file)
            [ "$#" -ge 2 ] || usage
            commit_file="$2"
            shift 2
            ;;
        --commit-range)
            [ "$#" -ge 2 ] || usage
            commit_range="$2"
            shift 2
            ;;
        --pr-title-file)
            [ "$#" -ge 2 ] || usage
            title_file="$2"
            shift 2
            ;;
        --pr-body-file)
            [ "$#" -ge 2 ] || usage
            body_file="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done

[ -n "$commit_file$title_file$body_file$commit_range" ] || usage

if [ -n "$commit_file" ]; then
    [ -f "$commit_file" ] || usage
    check_forbidden_file "$commit_file" 'commit message'
fi

if [ -n "$commit_range" ]; then
    umask 077
    message_file=$(mktemp "${TMPDIR:-/tmp}/closing-keyword-message.XXXXXX") || {
        printf '%s\n' 'closing-keyword guard: private workspace unavailable.' >&2
        exit 2
    }
    trap 'rm -f "$message_file"' EXIT HUP INT TERM
    commits=$(git rev-list --reverse "$commit_range" 2>/dev/null) || {
        printf '%s\n' 'closing-keyword guard: commit range unavailable.' >&2
        exit 2
    }
    for commit in $commits; do
        if ! git show -s --format=%B "$commit" >"$message_file" 2>/dev/null; then
            printf '%s\n' 'closing-keyword guard: commit message unavailable.' >&2
            exit 2
        fi
        check_forbidden_file "$message_file" 'commit message'
    done
    rm -f "$message_file"
    trap - EXIT HUP INT TERM
fi

if [ -n "$title_file" ]; then
    [ -f "$title_file" ] || usage
    check_forbidden_file "$title_file" 'pull request title'
fi

if [ -n "$body_file" ]; then
    [ -f "$body_file" ] || usage
    check_pr_body "$body_file"
fi

printf '%s\n' 'closing-keyword guard: PASS'
