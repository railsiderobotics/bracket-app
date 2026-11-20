"""
Fill a LOCAL database with demo bots (and optionally play rounds) so you can click
around and troubleshoot without Render, Neon, or typing in a whole bot list.

Examples:
    python seed_demo.py                          # 12 demo bots in 3lb
    python seed_demo.py --bots 16 --class 1lb    # 16 bots in 1lb
    python seed_demo.py --play stage1            # also draw and play Stage 1 (random winners)
    python seed_demo.py --play all               # play everything up to a champion
    python seed_demo.py --fresh --play stage1    # delete bracket.db first

Only works on the local SQLite database: it refuses to run if DATABASE_URL points anywhere else.
Needs SECRET_KEY and APP_PASSWORD in .env (see .env.example).
"""
import argparse
import os
import random
import sys

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bots', type=int, default=12, help='number of demo bots to add (default 12)')
    parser.add_argument('--class', dest='bot_class', default='3lb', choices=['3lb', '1lb', '1lb_plant'])
    parser.add_argument('--play', choices=['none', 'r1', 'stage1', 'all'], default='none',
                        help='r1 = Round 1 only; stage1 = Rounds 1, 2 and decider; all = through the final')
    parser.add_argument('--fresh', action='store_true', help='delete the local bracket.db first')
    parser.add_argument('--seed', type=int, help='random seed, to get the same results every time')
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASEDIR, '.env'))
    if os.environ.get('DATABASE_URL', '').strip() and not os.environ['DATABASE_URL'].startswith('sqlite'):
        sys.exit('DATABASE_URL points at a real database. This script only seeds the local SQLite file; '
                 'remove DATABASE_URL from .env (or this terminal) first.')
    if args.fresh:
        db_file = os.path.join(BASEDIR, 'bracket.db')
        if os.path.exists(db_file):
            os.remove(db_file)

    import app as appmod
    from models import db, Match

    rng = random.Random(args.seed)
    app = appmod.app
    appmod.limiter.enabled = False
    client = app.test_client()
    if client.post('/login', data={'password': os.environ.get('APP_PASSWORD', '')}).status_code != 302:
        sys.exit('Login failed: check APP_PASSWORD in .env')
    cls = args.bot_class
    q = f'?class={cls}'

    with app.app_context():
        taken = {name for (name,) in db.session.query(appmod.Team.name)}
    names, i = [], 1
    while len(names) < args.bots:
        name = f'Demo{cls}-{i:02d}'.replace('_', '')
        if name not in taken:
            names.append(name)
        i += 1
    # Bulk add splits on the first '-', so build "Bot-Team" pairs without extra dashes in the bot name.
    entries = [f"{n.replace('-', '')}-Team {k + 1}" for k, n in enumerate(names)]
    client.post(f'/teams{q}', data={'action': 'bulk_add', 'bot_class': cls, 'bulk_bots': ', '.join(entries)})
    print(f'Added {len(entries)} demo bots to {cls}.')

    def matches(stage, rnd=1):
        with app.app_context():
            return [(m.id, m.team1_id, m.team2_id, m.winner_id, m.is_bye)
                    for m in Match.query.filter_by(stage=stage, round_num=rnd, bot_class=cls).order_by(Match.slot_index)]

    def play_round(path, stage):
        client.post(f'{path}{q}', data={'action': 'generate'})
        client.post(f'{path}{q}', data={'action': 'lock'})
        for mid, t1, t2, winner, bye in matches(stage):
            if not bye and winner is None:
                client.post(f'{path}{q}', data={'action': 'results', f'winner_{mid}': rng.choice([t1, t2]),
                                                f'result_type_{mid}': rng.choice(['KO', 'JD', 'TO'])})
        print(f'Played {stage}.')

    if args.play == 'none':
        return
    play_round('/round/s1_r1', 's1_r1')
    if args.play == 'r1':
        return
    play_round('/round/s1_r2', 's1_r2')
    with app.test_request_context():
        need_decider = len(appmod.stage1_buckets(cls)[1]) > 0
    if need_decider:
        play_round('/round/decider', 'decider')
    if args.play == 'stage1':
        return

    client.post(f'/stage2/bracket{q}', data={'action': 'generate_round1'})
    rnd = 1
    while matches('s2', rnd):
        current = matches('s2', rnd)
        for mid, t1, t2, winner, bye in current:
            if not bye and winner is None:
                client.post(f'/stage2/{rnd}{q}', data={'action': 'results', f'winner_{mid}': rng.choice([t1, t2])})
        if len(current) == 1:
            break
        client.post(f'/stage2/{rnd}{q}', data={'action': 'generate_next'})
        rnd += 1
    for mid, t1, t2, winner, bye in matches('s2_placement'):
        if winner is None:
            client.post(f'/stage2/{rnd}{q}', data={'action': 'results', f'winner_{mid}': rng.choice([t1, t2])})
    print('Played Stage 2 through the final.')


if __name__ == '__main__':
    main()
