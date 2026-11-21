# Records docs/demo/fleet.gif. Needs vhs, ttyd and ffmpeg on PATH:
#   vhs docs/demo/demo.tape      (run from the repository root)
# Everything shown is fictional and runs in a throwaway home under /tmp/demo.
Output docs/demo/fleet.gif

Set Shell bash
Set FontSize 15
Set Width 1080
Set Height 420
Set Padding 14
Set Theme "Dracula"
Set TypingSpeed 22ms
Set PlaybackSpeed 1

Hide
Type "sh docs/demo/setup.sh prepare && exec env -i HOME=/tmp/demo PATH=/tmp/demo/bin:/usr/local/bin:/usr/bin:/bin TERM=xterm-256color PS1='$ ' bash --noprofile --norc"
Enter
Type "cd /tmp/demo/acme-app && clear"
Enter
Sleep 500ms
Show

Type "fleet init"
Enter
Sleep 1500ms
Hide
Type "demo-seed && clear"
Enter
Sleep 2500ms
Show

Type "fleet status --stale-ok"
Enter
Sleep 1500ms

Type "fleet msg send docs-fix 'rebase on main, then run checks' --from supervisor"
Enter
Sleep 1500ms

Type "fleet msg inbox --peek docs-fix"
Enter
Sleep 2500ms
