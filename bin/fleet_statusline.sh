#!/bin/sh
# claude-fleet statusline reader (docs/specs/terminal-surface.md §4.3).
#
# Usage: sh fleet_statusline.sh CACHE_DIR   (installed by `fleet init --statusline`)
#
# Prints the row fleet already rendered for this session. Fleet verbs that
# write state, and every keeper tick, re-render the cache
# (`fleet.refresh_statusline_cache`); this script only picks one file by the
# stdin blob's session id and $TMUX_PANE and prints it. It uses shell builtins
# only -- no python, no fork, no registry, log, transcript or process read --
# so a call costs one sh start. The one exception is opt-in: chained
# statusline commands (`fleet init --statusline --chain`) run first, as they
# would have without fleet. Exit 0 on every path, printing nothing on error.

cache=${1-}
[ -n "$cache" ] && [ -d "$cache" ] || exit 0

blob=
while IFS= read -r line || [ -n "$line" ]; do
    blob="$blob$line
"
done

suffix=
[ -n "${NO_COLOR-}" ] && suffix=.nocolor

# The chained delegates, one command per line, each fed the blob.
# A delegate that fails, or outlives 4 s where `timeout` exists, is dropped.
if [ -s "$cache/delegates" ]; then
    limit=
    command -v timeout >/dev/null 2>&1 && limit="timeout 4"
    while IFS= read -r command || [ -n "$command" ]; do
        [ -n "$command" ] || continue
        if rows=$(printf '%s' "$blob" | $limit sh -c "$command" 2>/dev/null); then
            [ -n "$rows" ] && printf '%s\n' "$rows"
        fi
    done < "$cache/delegates"
fi

# The blob's "session_id" value, by parameter expansion.
sid=
has_sid=
case $blob in
    *'"session_id"'*)
        rest=${blob#*\"session_id\"}
        rest=${rest#*:}
        rest=${rest#"${rest%%[![:space:]]*}"}
        case $rest in
            \"*)
                rest=${rest#\"}
                sid=${rest%%\"*}
                [ -n "$sid" ] && has_sid=1
                ;;
        esac
        ;;
esac
case $sid in
    *[!A-Za-z0-9_-]*) sid= ;;
esac

pane=
case ${TMUX_PANE-} in
    %[0-9]*)
        pane=${TMUX_PANE#%}
        case $pane in *[!0-9]*) pane= ;; esac
        ;;
esac

if [ -n "$pane" ] && [ -f "$cache/pane-$pane$suffix" ]; then
    file="$cache/pane-$pane$suffix"
elif [ -n "$sid" ] && [ -f "$cache/sid-$sid$suffix" ]; then
    file="$cache/sid-$sid$suffix"
elif [ -n "$has_sid" ]; then
    file="$cache/unregistered$suffix"
else
    file="$cache/nosid$suffix"
fi
[ -f "$file" ] || exit 0
while IFS= read -r row || [ -n "$row" ]; do
    printf '%s\n' "$row"
done < "$file"
exit 0
