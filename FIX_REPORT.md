# Bracket App: Bug Fix Report (2026-11-17)

Every bug below was first reproduced on the original code with an end-to-end script that drives the app through its real pages (Flask test client, throwaway SQLite DB), then re-checked after the fix.

| | Original | Fixed |
|---|---|---|
| Targeted bug checks | 1 / 21 pass | 21 / 21 pass |
| Full tournaments, 2 to 17 bots, random winners | 16 / 16 complete | 16 / 16 complete |
| Every page, logged in and public, every class, before and after a tournament | crashes (bracket overlay) | all return 200 |

The happy path (enter every result correctly, once, on one device) already worked. The bugs are in what happens at a real event: several devices, old tabs, the back button, re-queues, corrections, and edge-case bot counts.

## Data-loss bugs

**1. A stale results page wiped other people's results.** Clicking a winner submits the whole round form, including every *other* match's winner as it was when the page loaded. So if someone entered Match 1 on another device (or in another tab, or you hit Back), then you clicked Match 2 on the old page, Match 1 was silently reset to "no winner" and sent back to the queue.
*Fix:* results forms now also send the value each match had when the page loaded (`orig_winner_*`, `orig_result_type_*`), and the server only saves matches whose value you actually changed (`form_value_changed()` in `app.py`). Applies to Stage 1, the decider, and all Stage 2 forms.

**2. Re-sending "Advance to Next Round" wiped the next round.** A double-click or Back + resubmit deleted and rebuilt the next Stage 2 round, erasing results already entered there (including the final).
*Fix:* `generate_next` does nothing if the next round already exists, and refuses to run until every match in the current round has a winner.

**3. Stage 2 results could be changed after their winners had advanced.** A stale form could flip a Round 1 winner after Round 2 was built, leaving the bracket inconsistent (the new winner never appears in Round 2).
*Fix:* once the next round exists, that round's results are locked with an error message.

**4. A stray "Generate" POST re-drew a locked round, deleting its results.** The button is hidden once a round is locked, but the server didn't check (Back button or double-submit).
*Fix:* re-drawing or editing pairings is refused once the round is locked or the next round has been drawn, or while one of its matches is in progress.

**5. "Re-queue to Bottom" on a bye deleted the bye's automatic win.** Byes showed up under Completed Matches with a re-queue button; using it left the round permanently incomplete.
*Fix:* byes are no longer listed there, and the server refuses to re-queue them.

## Queue bugs

**6. "Re-queue to Bottom" usually put the match at the top.** Matches nobody has dragged have no queue number and sort last; the re-queued match got a number, so it jumped ahead of all of them.
*Fix:* `move_match_to_queue_bottom()` numbers the whole queue in its current order first, then puts the match last.

**7. Entering a result left the match "in progress" forever.** If a result was entered on the round page without first pressing "Move to Results Queue", the queue and the competitor dashboard kept showing it as the current match and blocked "Start Match" for the next one.
*Fix:* saving a winner marks the match `completed`; the in-progress lookup also ignores matches that have a winner.

**8. The competitor dashboard showed a different order than the admin queue.** It sorted un-dragged matches first instead of last.
*Fix:* it now uses the same ordering as the admin queue and the overlay.

**9. Re-queuing a finished Stage 1 match flipped the whole round back to "edit pairings" mode.** It unlocked the match, so the round page stopped showing results.
*Fix:* re-queue now uses the same path as clearing a result on the round page. Stage 1 rounds stay locked; Stage 2 final/bronze matches still unlock so a new result can be entered. Re-queuing a Stage 2 match whose winner already advanced is refused.

## Pairing and seeding bugs

**10. Round 2 match numbers were duplicated.** Winners' and losers' groups both started at slot 0, so Round 2 showed as Match 1, Match 1, Match 2, Match 2 interleaved.
*Fix:* numbering continues across both groups.

**11. A bot could get two free wins.** A bot with a Stage 1 bye could also draw the decider bye and reach Stage 2 having won only one real fight (or none). Seen in 2 of 40 random test tournaments.
*Fix:* the decider bye skips bots that already had a Stage 1 bye (unless every bot in the pool did).

**12. Pairing edits could drop or double up bots.** The "each bot once" check ignored the bye bot (it could be placed in a second match), allowed swapping in a bot that wasn't in the round (silently removing another), and the decider dropdowns offered every bot, including 2-0 and 0-2 bots.
*Fix:* edits can only rearrange the bots already in that round, each exactly once, and the dropdowns only list those bots.

**13. The decider could be generated before Stage 1 was finished** (by URL), missing bots whose results weren't in yet.
*Fix:* refused until Rounds 1 and 2 are complete.

**14. Generating Stage 2 with fewer than 2 qualifiers crashed (error 500).** It also ran even if Stage 1 wasn't finished.
*Fix:* both checks added with clear messages. The duplicated bracket-generation code in two routes is now one function, `generate_stage2_round1()`.

**15. The bracket preview was sized for every bot, not the qualifiers.** With 16 bots and 8 qualifiers it showed a 4-round bracket instead of 3.
*Fix:* once Stage 1 is done, the preview uses the real qualifier count.

## Timer bugs

**16. "+20m Extension" was wasted if the bot's timer had already run out.** It added 20 minutes to an end time hours in the past, so nothing happened, but the extension was still marked as used.
*Fix:* the extension adds 20 minutes to whatever time is left, counting an expired timer as 0 left.

**17. Fixing a mis-clicked winner restarted both bots' 20-minute repair timers.**
*Fix:* timers only start the first time a match gets a result.

## Page and security bugs

**18. The public standings page could show the admin navbar** (Reset Tournament, etc.) to everyone for 15 s, because the cached copy was whatever the first visitor saw, admin included. It could also cache someone's flash message.
*Fix:* admins and anyone with a pending message skip the cache.

**19. The bracket overlay crashed (error 500) for a class with no bots.**
*Fix:* the template handles an empty bracket.

**20. Destructive buttons had no confirmation.** "Reset Tournament" sits in the navbar next to Settings and Logout and wipes every match in every class with one click; "Delete" and "Clear All" on the bots page were the same.
*Fix:* all three ask for confirmation first (`data-confirm` + a small handler in `base.html`).

**21. Session cookie hardening.** No CSRF protection exists, so another website could submit admin forms with a logged-in admin's cookie in browsers that don't default to SameSite=Lax.
*Fix:* `SESSION_COOKIE_SAMESITE='Lax'`, and `SESSION_COOKIE_SECURE` when running on Render (`RENDER` env var).

**Small fixes:** stray `</ul>` closing a `<div>` on the repair timers page; seconds now zero-padded (`4m 05s`); bad ids in forms no longer cause a 500; `request.get_json(silent=True)` on the reorder API; deprecated `Query.get()` and `datetime.utcnow()` replaced (`db.session.get()`, `utcnow()` helper).

## Related branch

Instructions for running and testing the app on your own computer (no Render or Neon needed), plus a demo-data script, are on the separate branch `feature/local-testing`.

## Behavior changes to know about

- Results are now saved per match you change, not per page. Two people changing the *same* match: last save wins.
- Changing a Stage 1 or decider result after the next round was drawn now shows a warning to re-check that round's pairings. It is still allowed, so you can fix mistakes.
- Re-queuing a Stage 2 match whose winner already advanced is refused.
- A bot can't take the decider bye if it already had a Stage 1 bye.

## Not changed (worth a decision)

- **The queue shows pairings before the round is locked.** Competitors can see (and the queue can start) matches that may still be re-drawn. Consider only queuing locked rounds.
- **Stage 1 results stay editable after later rounds are drawn** (now with a warning). Locking them would block legitimate corrections.
- **Bulk add splits on the first `-`**, so a bot named `T-Rex` becomes bot `T`, team `Rex-...`. Use the single add form for those, or change the separator in both the app and the Excel generator.
- **No CSRF tokens.** SameSite=Lax covers the realistic risk; full tokens (Flask-WTF) would touch every form.
- **Login rate limit is per IP, but behind Render's proxy every visitor may share one IP**, so 5 bad attempts per minute could lock out all admins briefly. Werkzeug's `ProxyFix` would fix it, but I didn't confirm how many proxy hops Render adds, so I left it.
- **`templates/bracket.html` is unused** (no route renders it) and has outdated logic. Safe to delete.

## Not verified

- Only tested against SQLite locally. Nothing changed the schema, but it was not run against the Neon Postgres database.
- The browser check covered the round page (stale-page fix with a real click), the confirm dialogs, checkbox saving on the bots page, the queue, and the repair timers page. Overlays were only checked for load errors, not looks.
