import math
import os
import random
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from sqlalchemy import inspect, or_, text
from dotenv import load_dotenv

from models import db, Team, Match, TournamentSetting
from bracket_logic import random_pairs, build_bracket_slots, round_pairs_from_slots, next_pow2

# ---------- Environment & Configuration Setup ----------

BASEDIR = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from local .env file
load_dotenv(os.path.join(BASEDIR, '.env'))

# Read secrets securely from environment variables
SECRET_KEY = os.environ.get("SECRET_KEY")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

if not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD environment variable is missing! Make sure it is defined in your .env file or host environment.")

app = Flask(__name__, static_folder='Image Files')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASEDIR, 'bracket.db')
app.config['SECRET_KEY'] = SECRET_KEY or "dev-key-change-in-production"
db.init_app(app)

STAGE1_ROUNDS = ['s1_r1', 's1_r2']
STAGE_LABELS = {
    's1_r1': 'Stage 1 – Round 1',
    's1_r2': 'Stage 1 – Round 2',
    'decider': 'Decider Round (1-1 bots)',
}
BOT_CLASSES = ['3lb', '1lb', '1lb_plant']
CLASS_LABELS = {
    '3lb': '3lb Beetleweights',
    '1lb': '1lb Antweights',
    '1lb_plant': '1lb PLANT',
}

# ---------- Auth Helpers & Context ----------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            flash("Please log in as Admin to access this page.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_auth_status():
    return dict(is_authenticated=session.get("authenticated", False))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == APP_PASSWORD:
            session["authenticated"] = True
            flash("Successfully logged in as Admin!", "info")
            return redirect(url_for("index"))
        else:
            flash("Invalid password! Please try again.", "error")
            return redirect(url_for("login"))
            
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


with app.app_context():
    db.create_all()
    insp = inspect(db.engine)
    team_columns = [c['name'] for c in insp.get_columns('team')]
    if 'assigned_team_name' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN assigned_team_name VARCHAR(80) DEFAULT ""'))
    if 'bot_class' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN bot_class VARCHAR(20) DEFAULT "3lb"'))
    if 'checked_in' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN checked_in BOOLEAN DEFAULT 0'))
    if 'safety_waiver' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN safety_waiver BOOLEAN DEFAULT 0'))
    if 'registration_fee' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN registration_fee BOOLEAN DEFAULT 0'))
    if 'pit_table_number' not in team_columns:
        db.session.execute(text('ALTER TABLE team ADD COLUMN pit_table_number VARCHAR(20)'))

    match_columns = [c['name'] for c in insp.get_columns('match')]
    if 'bot_class' not in match_columns:
        db.session.execute(text('ALTER TABLE match ADD COLUMN bot_class VARCHAR(20) DEFAULT "3lb"'))
    if 'result_type' not in match_columns:
        db.session.execute(text('ALTER TABLE match ADD COLUMN result_type VARCHAR(10)'))
    if 'queue_status' not in match_columns:
        db.session.execute(text('ALTER TABLE match ADD COLUMN queue_status VARCHAR(20) DEFAULT "queued"'))
    if 'queue_order' not in match_columns:
        db.session.execute(text('ALTER TABLE match ADD COLUMN queue_order INTEGER DEFAULT 0'))

    existing_settings = {row.key for row in TournamentSetting.query.all()}
    for cls in BOT_CLASSES:
        if cls not in existing_settings:
            db.session.add(TournamentSetting(key=cls, enabled=True))
    db.session.commit()


# ---------- helpers ----------

def active_teams(bot_class=None):
    query = Team.query.filter_by(dropped=False)
    if bot_class:
        query = query.filter_by(bot_class=bot_class)
    return query.order_by(Team.name).all()


def matches_for(stage, round_num=None, bot_class=None):
    q = Match.query.filter_by(stage=stage)
    if round_num is not None:
        q = q.filter_by(round_num=round_num)
    if bot_class:
        q = q.filter_by(bot_class=bot_class)
    return q.order_by(Match.slot_index).all()


def round_generated(stage, round_num=1, bot_class=None):
    return len(matches_for(stage, round_num, bot_class)) > 0


def round_locked(stage, round_num=1, bot_class=None):
    ms = matches_for(stage, round_num, bot_class)
    return len(ms) > 0 and all(m.locked for m in ms)


def round_complete(stage, round_num=1, bot_class=None):
    ms = matches_for(stage, round_num, bot_class)
    return len(ms) > 0 and all(m.winner_id is not None for m in ms)


def stage1_records(bot_class=None):
    records = {t.id: [0, 0] for t in active_teams(bot_class)}
    for stage in STAGE1_ROUNDS:
        for m in matches_for(stage, bot_class=bot_class):
            if m.winner_id is None:
                continue
            participants = [tid for tid in (m.team1_id, m.team2_id) if tid is not None]
            for tid in participants:
                if tid not in records:
                    continue
                if tid == m.winner_id:
                    records[tid][0] += 1
                else:
                    records[tid][1] += 1
    return records


def stage1_buckets(bot_class=None):
    records = stage1_records(bot_class)
    teams_by_id = {t.id: t for t in active_teams(bot_class)}
    two_oh, one_one, oh_two, incomplete = [], [], [], []
    for tid, (w, l) in records.items():
        team = teams_by_id.get(tid)
        if team is None:
            continue
        if w + l < 2:
            incomplete.append(team)
        elif w == 2:
            two_oh.append(team)
        elif w == 1:
            one_one.append(team)
        else:
            oh_two.append(team)
    return two_oh, one_one, oh_two, incomplete


def stage1_round1_groups(bot_class=None):
    winners, losers = [], []
    for m in matches_for('s1_r1', 1, bot_class=bot_class):
        if m.is_bye:
            continue
        if m.winner_id is None:
            continue
        loser_id = m.team1_id if m.winner_id == m.team2_id else m.team2_id
        winners.append(m.winner_id)
        if loser_id is not None:
            losers.append(loser_id)
    return winners, losers


def stage1_team_groups(bot_class=None):
    winners, losers = stage1_round1_groups(bot_class)
    groups = {tid: 'winner' for tid in winners}
    groups.update({tid: 'loser' for tid in losers})
    return groups


def lock_stage1_round1(bot_class=None):
    for m in matches_for('s1_r1', 1, bot_class=bot_class):
        m.locked = True
    db.session.commit()


def lock_stage2_prereqs(bot_class=None):
    for stage in ('s1_r1', 's1_r2', 'decider'):
        for m in matches_for(stage, 1, bot_class=bot_class):
            m.locked = True
    db.session.commit()


def create_stage1_round2_matches(bot_class):
    Match.query.filter_by(stage='s1_r2', round_num=1, bot_class=bot_class).delete()
    winners, losers = stage1_round1_groups(bot_class)
    for group in (winners, losers):
        pairs, bye = random_pairs(group)
        for i, (a, b) in enumerate(pairs):
            db.session.add(Match(stage='s1_r2', round_num=1, slot_index=i,
                                  team1_id=a, team2_id=b, bot_class=bot_class, locked=False))
        if bye is not None:
            db.session.add(Match(stage='s1_r2', round_num=1, slot_index=len(pairs),
                                  team1_id=bye, team2_id=None, bot_class=bot_class, is_bye=True,
                                  winner_id=bye, locked=True))
    lock_stage1_round1(bot_class)
    db.session.commit()


def stage1_stats(bot_class=None):
    stats = {}
    for t in active_teams(bot_class):
        stats[t.id] = {
            'team': t,
            'wins': 0,
            'losses': 0,
            'to': 0,
            'ko': 0,
            'jd': 0,
            'loss_to': 0,
            'loss_ko': 0,
            'loss_jd': 0,
            'record': '0-0',
        }
    for stage in STAGE1_ROUNDS + ['decider']:
        for m in matches_for(stage, bot_class=bot_class):
            if m.is_bye or m.winner_id is None:
                continue
            for tid in (m.team1_id, m.team2_id):
                if tid not in stats:
                    continue
                if tid == m.winner_id:
                    stats[tid]['wins'] += 1
                    if m.result_type == 'TO':
                        stats[tid]['to'] += 1
                    elif m.result_type == 'KO':
                        stats[tid]['ko'] += 1
                    elif m.result_type == 'JD':
                        stats[tid]['jd'] += 1
                else:
                    stats[tid]['losses'] += 1
                    if m.result_type == 'TO':
                        stats[tid]['loss_to'] += 1
                    elif m.result_type == 'KO':
                        stats[tid]['loss_ko'] += 1
                    elif m.result_type == 'JD':
                        stats[tid]['loss_jd'] += 1
    for stat in stats.values():
        stat['record'] = f"{stat['wins']}-{stat['losses']}"
    return stats


def stage1_standings(bot_class=None):
    stats = list(stage1_stats(bot_class).values())
    two_oh = [s for s in stats if s['wins'] == 2 and s['losses'] == 0]
    others = [s for s in stats if not (s['wins'] == 2 and s['losses'] == 0)]
    two_oh.sort(key=lambda item: (
        item['loss_to'],
        item['loss_ko'],
        -item['loss_jd'],
        item['team'].name
    ))
    others.sort(key=lambda item: (
        -item['wins'],
        item['loss_to'],
        item['loss_ko'],
        -item['loss_jd'],
        item['team'].name
    ))
    return two_oh + others


def get_class_settings():
    return {s.key: s.enabled for s in TournamentSetting.query.all()}


def enabled_classes():
    settings = get_class_settings()
    return [cls for cls in BOT_CLASSES if settings.get(cls, True)]


def class_decider_done(bot_class=None):
    decider_needed = round_complete('s1_r1', 1, bot_class) and round_complete('s1_r2', 1, bot_class) and len(stage1_buckets(bot_class)[1]) > 0
    if round_generated('decider', 1, bot_class):
        return round_complete('decider', 1, bot_class)
    return not decider_needed


def class_stage2_ready(bot_class=None):
    return round_complete('s1_r1', 1, bot_class) and round_complete('s1_r2', 1, bot_class) and class_decider_done(bot_class)


def stage2_placement_match(bot_class=None):
    matches = Match.query.filter_by(stage='s2_placement', bot_class=bot_class).order_by(Match.slot_index).all()
    return matches[0] if matches else None


def stage2_qualifiers(bot_class=None):
    standings = stage1_standings(bot_class)
    two_oh = [stat['team'].id for stat in standings if stat['wins'] == 2 and stat['losses'] == 0]
    decider_winners = {m.winner_id for m in matches_for('decider', 1, bot_class=bot_class) if m.winner_id}
    decider_order = [stat['team'].id for stat in standings if stat['team'].id in decider_winners]
    return two_oh + decider_order


def current_selected_class(default='3lb'):
    selected = request.values.get('class')
    enabled = enabled_classes()
    if selected in enabled:
        return selected
    for cls in enabled:
        if class_stage2_ready(cls):
            return cls
    return enabled[0] if enabled else default


def create_round_matches(stage, team_ids, round_num=1, bot_class='3lb', rng=None):
    Match.query.filter_by(stage=stage, round_num=round_num, bot_class=bot_class).delete()
    shuffled_ids = list(team_ids)
    random.shuffle(shuffled_ids)
    
    pairs, bye = random_pairs(shuffled_ids, rng=rng)
    for i, (a, b) in enumerate(pairs):
        db.session.add(Match(stage=stage, round_num=round_num, slot_index=i,
                              team1_id=a, team2_id=b, bot_class=bot_class, locked=False))
    if bye is not None:
        db.session.add(Match(stage=stage, round_num=round_num, slot_index=len(pairs),
                              team1_id=bye, team2_id=None, bot_class=bot_class, is_bye=True,
                              winner_id=bye, locked=True))
    db.session.commit()


def stage2_bracket_data(bot_class=None):
    round1 = matches_for('s2', 1, bot_class=bot_class)
    if not round1:
        count = len(active_teams(bot_class))
        if count == 0:
            return None
        slot_count = next_pow2(count)
        if slot_count < 2:
            slot_count = 2
        total_rounds = int(math.log2(slot_count))
        rounds = []
        for r in range(1, total_rounds + 1):
            matches_in_round = slot_count // (2 ** r)
            placeholders = [{'team1': None, 'team2': None, 'winner': None, 'generated': False, 'is_bye': False} for _ in range(matches_in_round)]
            rounds.append({'round': r, 'matches': placeholders, 'generated': False})
        return rounds

    slot_count = len(round1) * 2
    total_rounds = int(math.log2(slot_count))
    rounds = []

    for r in range(1, total_rounds + 1):
        actual = matches_for('s2', r, bot_class=bot_class)
        if actual:
            rounds.append({'round': r, 'matches': actual, 'generated': True})
            continue

        prev = rounds[r - 2]['matches'] if r > 1 else []
        placeholders = []
        winners = []
        for m in prev:
            if isinstance(m, Match):
                if m.winner_id is not None:
                    winners.append(m.winner_id)
                elif m.is_bye and m.team1_id is not None:
                    winners.append(m.team1_id)
                else:
                    winners.append(None)
            else:
                winners.append(m.get('winner'))
        for i in range(0, len(winners), 2):
            a = winners[i]
            b = winners[i + 1] if i + 1 < len(winners) else None
            placeholders.append({
                'team1': Team.query.get(a) if a else None,
                'team2': Team.query.get(b) if b else None,
                'winner': a if b is None else None,
                'generated': False,
                'is_bye': b is None and a is not None,
            })
        rounds.append({'round': r, 'matches': placeholders, 'generated': False})

    return rounds


# ---------- dashboard & competitor routes ----------

@app.route('/')
def index():
    if not session.get("authenticated"):
        return redirect(url_for("competitor_dashboard"))

    teams = active_teams()
    two_oh, one_one, oh_two, incomplete = ([], [], [], [])
    enabled = enabled_classes()
    current_class = current_selected_class('3lb')
    s1_done = round_complete('s1_r1') and round_complete('s1_r2')
    if s1_done:
        two_oh, one_one, oh_two, incomplete = stage1_buckets()

    decider_needed = s1_done and len(one_one) > 0
    decider_done = round_complete('decider') if round_generated('decider') else (decider_needed is False and s1_done)

    stage2_started = round_generated('s2', 1)
    stage2_ready_class = next((cls for cls in enabled if class_stage2_ready(cls)), None)

    return render_template('index.html', teams=teams, s1_done=s1_done,
                           two_oh=two_oh, one_one=one_one, oh_two=oh_two,
                           incomplete=incomplete, decider_needed=decider_needed,
                           decider_generated=round_generated('decider'),
                           decider_done=decider_done, stage2_started=stage2_started,
                           stage2_ready_class=stage2_ready_class,
                           current_class=current_class)


@app.route('/competitor')
def competitor_dashboard():
    current_class = current_selected_class('3lb')
    enabled = enabled_classes()

    in_progress = Match.query.filter_by(bot_class=current_class, queue_status='in_progress').first()
    queued_matches = Match.query.filter_by(bot_class=current_class, queue_status='queued', winner_id=None)\
                               .order_by(Match.queue_order.asc()).all()
    bracket = stage2_bracket_data(current_class)
    placement_match = stage2_placement_match(current_class)
    champion = None

    if bracket and len(bracket) > 0:
        last = bracket[-1]
        if last.get('matches'):
            final_match = last['matches'][0]
            if isinstance(final_match, Match) and final_match.winner_id:
                champion = final_match.winner
            elif isinstance(final_match, dict) and final_match.get('winner'):
                champion = Team.query.get(final_match.get('winner'))

    return render_template('competitor_dashboard.html',
                           in_progress=in_progress,
                           queued_matches=queued_matches,
                           bracket=bracket,
                           placement_match=placement_match,
                           champion=champion,
                           current_class=current_class,
                           BOT_CLASSES=enabled,
                           CLASS_LABELS=CLASS_LABELS)


@app.route('/results')
def competitor_results():
    current_class = request.args.get('class', '3lb')
    enabled = enabled_classes()
    if current_class not in enabled:
        current_class = enabled[0] if enabled else '3lb'

    all_matches = Match.query.filter_by(bot_class=current_class)\
                             .order_by(Match.stage, Match.round_num, Match.slot_index).all()

    # Calculate maximum round generated in Stage 2 to identify finals
    s2_max_round = db.session.query(db.func.max(Match.round_num))\
                            .filter_by(bot_class=current_class, stage='s2').scalar() or 1

    grouped_matches = {}
    for m in all_matches:
        if m.stage == 's1_r1':
            label = STAGE_LABELS['s1_r1']
        elif m.stage == 's1_r2':
            label = STAGE_LABELS['s1_r2']
        elif m.stage == 'decider':
            label = STAGE_LABELS['decider']
        elif m.stage == 's2':
            # Check if this stage 2 round is the final match (only 1 slot/match or max round)
            round_matches_count = Match.query.filter_by(bot_class=current_class, stage='s2', round_num=m.round_num).count()
            if round_matches_count == 1 or m.round_num == s2_max_round:
                label = "Stage 2 — Finals Match"
            else:
                label = f"Stage 2 — Round {m.round_num}"
        elif m.stage == 's2_placement':
            label = "Stage 2 — Bronze Placement Match"
        else:
            label = m.stage

        if label not in grouped_matches:
            grouped_matches[label] = []
        grouped_matches[label].append(m)

    return render_template('competitor_results.html',
                           grouped_matches=grouped_matches,
                           current_class=current_class,
                           BOT_CLASSES=enabled,
                           CLASS_LABELS=CLASS_LABELS)


@app.route('/standings')
def standings():
    current_class = request.args.get('class', '3lb')
    if current_class not in enabled_classes():
        current_class = enabled_classes()[0] if enabled_classes() else '3lb'
    standings = stage1_standings(current_class)
    return render_template('standings.html', standings=standings,
                           current_class=current_class,
                           BOT_CLASSES=enabled_classes(),
                           CLASS_LABELS=CLASS_LABELS)


# ---------- teams ----------

@app.route('/teams', methods=['GET', 'POST'])
@login_required
def teams():
    current_class = current_selected_class('3lb')

    if request.method == 'POST':
        action = request.form.get('action')
        bot_class = request.form.get('bot_class', current_class)
        if bot_class not in BOT_CLASSES:
            bot_class = '3lb'

        if action == 'add':
            bot_name = request.form.get('bot_name', '').strip()
            assigned_team_name = request.form.get('assigned_team_name', '').strip()
            checked_in = bool(request.form.get('checked_in'))
            safety_waiver = bool(request.form.get('safety_waiver'))
            pit_table_number = request.form.get('pit_table_number', '').strip() or None
            if bot_name and assigned_team_name:
                if Team.query.filter_by(name=bot_name).first():
                    flash(f'Bot "{bot_name}" already exists.', 'error')
                else:
                    db.session.add(Team(name=bot_name, assigned_team_name=assigned_team_name,
                                        bot_class=bot_class, checked_in=checked_in,
                                        safety_waiver=safety_waiver, pit_table_number=pit_table_number))
                    db.session.commit()
            else:
                flash('Please provide both a bot name and the assigned team name.', 'error')
        elif action == 'bulk_add':
            bulk = request.form.get('bulk_bots', '').strip()
            entries = [entry.strip() for entry in bulk.split(',') if entry.strip()]
            added = 0
            skipped = []
            for entry in entries:
                if '-' not in entry:
                    skipped.append(f'Invalid format: {entry}')
                    continue
                bot_name, assigned_team_name = [part.strip() for part in entry.split('-', 1)]
                if not bot_name or not assigned_team_name:
                    skipped.append(f'Invalid pair: {entry}')
                    continue
                if Team.query.filter_by(name=bot_name).first():
                    skipped.append(f'Bot "{bot_name}" already exists')
                    continue
                db.session.add(Team(name=bot_name, assigned_team_name=assigned_team_name,
                                    bot_class=bot_class))
                added += 1
            if added > 0:
                db.session.commit()
                flash(f'Added {added} bots.', 'info')
            if skipped:
                flash('Bulk add skipped: ' + '; '.join(skipped), 'error')
        elif action == 'edit':
            tid = request.form.get('team_id')
            if tid:
                t = Team.query.get(int(tid))
                if t:
                    bot_name = request.form.get(f'bot_name_{t.id}')
                    assigned_team_name = request.form.get(f'assigned_team_name_{t.id}')
                    pit_table_number = request.form.get(f'pit_table_number_{t.id}')
                    checked_in = bool(request.form.get(f'checked_in_{t.id}'))
                    safety_waiver = bool(request.form.get(f'safety_waiver_{t.id}'))
                    registration_fee = bool(request.form.get(f'registration_fee_{t.id}'))
                    bot_class_value = request.form.get(f'bot_class_{t.id}', t.bot_class)
                    if bot_class_value not in BOT_CLASSES:
                        bot_class_value = t.bot_class
                    if bot_name is not None and assigned_team_name is not None:
                        bot_name = bot_name.strip()
                        assigned_team_name = assigned_team_name.strip()
                        if not bot_name or not assigned_team_name:
                            flash('Bot name and assigned team name are required.', 'error')
                            return redirect(url_for('teams', **{'class': bot_class}))
                        duplicate = Team.query.filter(Team.name == bot_name, Team.id != t.id).first()
                        if duplicate:
                            flash(f'Bot "{bot_name}" already exists.', 'error')
                            return redirect(url_for('teams', **{'class': bot_class}))
                        t.name = bot_name
                        t.assigned_team_name = assigned_team_name
                    if pit_table_number is not None:
                        t.pit_table_number = pit_table_number.strip() or None
                    t.checked_in = checked_in
                    t.safety_waiver = safety_waiver
                    t.registration_fee = registration_fee
                    t.bot_class = bot_class_value
                    db.session.commit()
        elif action == 'delete':
            tid = request.form.get('team_id')
            if tid:
                t = Team.query.get(int(tid))
                if t:
                    Match.query.filter(or_(Match.team1_id == t.id,
                                            Match.team2_id == t.id,
                                            Match.winner_id == t.id)).delete(synchronize_session=False)
                    db.session.delete(t)
                    db.session.commit()
        elif action == 'clear_all':
            Match.query.filter_by(bot_class=bot_class).delete(synchronize_session=False)
            Team.query.filter_by(bot_class=bot_class).delete(synchronize_session=False)
            db.session.commit()
            flash(f'All {CLASS_LABELS[bot_class]} bots cleared.', 'info')
        return redirect(url_for('teams', **{'class': bot_class}))

    all_teams = Team.query.filter_by(bot_class=current_class).order_by(Team.name).all()
    return render_template('teams.html', teams=all_teams, current_class=current_class,
                           BOT_CLASSES=enabled_classes(), CLASS_LABELS=CLASS_LABELS)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        for cls in BOT_CLASSES:
            enabled_value = bool(request.form.get(f'enabled_{cls}'))
            setting = TournamentSetting.query.filter_by(key=cls).first()
            if setting:
                setting.enabled = enabled_value
            else:
                db.session.add(TournamentSetting(key=cls, enabled=enabled_value))
        db.session.commit()
        flash('Global tournament settings updated.', 'info')
        return redirect(url_for('settings'))

    settings = TournamentSetting.query.order_by(TournamentSetting.key).all()
    return render_template('settings.html', settings=settings, CLASS_LABELS=CLASS_LABELS)


# ---------- stage 1 rounds & decider round (shared workflow) ----------

def round_view(stage, round_num, team_id_source, back_url, generate_func=None):
    bot_class = request.values.get('class')
    enabled = enabled_classes()
    if bot_class not in enabled:
        bot_class = enabled[0] if enabled else '3lb'
    label = f"{STAGE_LABELS[stage]} — {CLASS_LABELS[bot_class]}"

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            if generate_func:
                if stage == 's1_r2' and not round_complete('s1_r1', 1, bot_class):
                    flash('Finish Round 1 results before opening Round 2.', 'error')
                    return redirect(url_for(request.endpoint, **{'class': bot_class}))
                generate_func(bot_class)
            else:
                ids = team_id_source(bot_class)
                create_round_matches(stage, ids, round_num, bot_class=bot_class)
            return redirect(url_for(request.endpoint, **{'class': bot_class}))
        elif action == 'save_edits':
            ms = matches_for(stage, round_num, bot_class=bot_class)
            assigned = set()
            groups = stage1_team_groups(bot_class) if stage == 's1_r2' else {}
            for m in ms:
                if m.is_bye:
                    continue
                t1 = int(request.form.get(f'team1_{m.id}'))
                t2 = int(request.form.get(f'team2_{m.id}'))
                if t1 == t2 or t1 in assigned or t2 in assigned:
                    flash('Each bot must appear exactly once. No changes saved.', 'error')
                    return redirect(url_for(request.endpoint, **{'class': bot_class}))
                if stage == 's1_r2' and groups.get(t1) != groups.get(t2):
                    flash('Round 2 pairings must match winners with winners and losers with losers.', 'error')
                    return redirect(url_for(request.endpoint, **{'class': bot_class}))
                assigned.add(t1)
                assigned.add(t2)
                m.team1_id, m.team2_id = t1, t2
            db.session.commit()
            return redirect(url_for(request.endpoint, **{'class': bot_class}))
        elif action == 'lock':
            for m in matches_for(stage, round_num, bot_class=bot_class):
                m.locked = True
            db.session.commit()
            return redirect(url_for(request.endpoint, **{'class': bot_class}) + '#results')
        elif action == 'results':
            for m in matches_for(stage, round_num, bot_class=bot_class):
                if m.is_bye:
                    continue
                w = request.form.get(f'winner_{m.id}')
                if w:
                    m.winner_id = int(w)
                m.result_type = request.form.get(f'result_type_{m.id}') or None
            db.session.commit()
            return redirect(url_for(request.endpoint, **{'class': bot_class}) + '#results')
        return redirect(url_for(request.endpoint, **{'class': bot_class}))

    generated = round_generated(stage, round_num, bot_class)
    locked = round_locked(stage, round_num, bot_class)
    complete = round_complete(stage, round_num, bot_class)
    if stage == 's1_r1' and round_generated('s1_r2', 1, bot_class):
        locked = True
    if stage == 's1_r2' and round_generated('decider', 1, bot_class):
        locked = True
    if stage == 'decider' and round_generated('s2', 1, bot_class):
        locked = True
    round1_ready = round_complete('s1_r1', 1, bot_class) if stage == 's1_r2' else True

    matches = matches_for(stage, round_num, bot_class=bot_class)
    all_active = active_teams(bot_class)
    extra_context = {}
    if stage == 's1_r2':
        extra_context['team_groups'] = stage1_team_groups(bot_class)
        extra_context['round1_ready'] = round1_ready
    return render_template('round.html', label=label, stage=stage, matches=matches,
                           generated=generated, locked=locked, complete=complete,
                           all_teams=all_active, back_url=back_url,
                           current_class=bot_class, BOT_CLASSES=enabled, CLASS_LABELS=CLASS_LABELS,
                           **extra_context)


@app.route('/round/s1_r1', methods=['GET', 'POST'])
@login_required
def s1_r1():
    return round_view('s1_r1', 1, lambda bot_class: [t.id for t in active_teams(bot_class)], url_for('index'))


@app.route('/round/s1_r2', methods=['GET', 'POST'])
@login_required
def s1_r2():
    return round_view('s1_r2', 1, lambda bot_class: [t.id for t in active_teams(bot_class)], url_for('index'), generate_func=create_stage1_round2_matches)


@app.route('/round/decider', methods=['GET', 'POST'])
@login_required
def decider():
    def decider_team_ids(bot_class):
        _, one_one, _, _ = stage1_buckets(bot_class)
        return [t.id for t in one_one]
    return round_view('decider', 1, decider_team_ids, url_for('index'))


# ---------- stage 2 bracket ----------

@app.route('/stage2/bracket', methods=['GET', 'POST'])
@login_required
def stage2_bracket():
    bot_class = request.values.get('class')
    enabled = enabled_classes()
    if bot_class not in enabled:
        bot_class = next((cls for cls in enabled if class_stage2_ready(cls)), None)
        bot_class = bot_class if bot_class else (enabled[0] if enabled else '3lb')

    last_key = f'stage2_last_round_{bot_class}'

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate_round1':
            try:
                qualifiers = stage2_qualifiers(bot_class)
            except Exception:
                flash('Seeding fallback: using current ranking due to incomplete data.', 'info')
                qualifiers = [stat['team'].id for stat in stage1_standings(bot_class)]
            slots = build_bracket_slots(qualifiers)
            Match.query.filter_by(stage='s2', bot_class=bot_class).delete()
            Match.query.filter_by(stage='s2_placement', bot_class=bot_class).delete()
            pairs = round_pairs_from_slots(slots)
            for i, (a, b) in enumerate(pairs):
                if a is None or b is None:
                    real = a if a is not None else b
                    db.session.add(Match(stage='s2', round_num=1, slot_index=i,
                                          team1_id=real, team2_id=None, bot_class=bot_class, is_bye=True,
                                          winner_id=real, locked=True))
                else:
                    db.session.add(Match(stage='s2', round_num=1, slot_index=i,
                                          team1_id=a, team2_id=b, bot_class=bot_class, locked=False))
            db.session.commit()
            lock_stage2_prereqs(bot_class)
            session[last_key] = 1
        return redirect(url_for('stage2_bracket', **{'class': bot_class}))

    bracket = stage2_bracket_data(bot_class)
    placement_match = stage2_placement_match(bot_class)
    qualifiers_ready = class_stage2_ready(bot_class)
    champion = None
    second_place = None
    third_place = None
    if bracket and len(bracket) > 0:
        last = bracket[-1]
        if last.get('matches'):
            final_match = last['matches'][0]
            if isinstance(final_match, Match) and final_match.winner_id:
                champion = final_match.winner
                if final_match.team1 and final_match.team2:
                    second_place = final_match.team2 if final_match.winner_id == final_match.team1_id else final_match.team1
            elif isinstance(final_match, dict) and final_match.get('winner'):
                champion = Team.query.get(final_match.get('winner'))
    if placement_match and placement_match.winner_id:
        third_place = placement_match.winner
    return render_template('stage2_bracket.html', bracket=bracket,
                           placement_match=placement_match,
                           qualifiers_ready=qualifiers_ready,
                           champion=champion, second_place=second_place, third_place=third_place,
                           current_class=bot_class, BOT_CLASSES=enabled,
                           CLASS_LABELS=CLASS_LABELS)


@app.route('/stage2/<int:round_num>', methods=['GET', 'POST'])
@login_required
def stage2(round_num):
    bot_class = request.values.get('class')
    enabled = enabled_classes()
    if bot_class not in enabled:
        bot_class = next((cls for cls in enabled if class_stage2_ready(cls)), None)
        bot_class = bot_class if bot_class else (enabled[0] if enabled else '3lb')

    last_key = f'stage2_last_round_{bot_class}'

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate_round1':
            try:
                qualifiers = stage2_qualifiers(bot_class)
            except Exception:
                flash('Seeding fallback: using current ranking due to incomplete data.', 'info')
                qualifiers = [stat['team'].id for stat in stage1_standings(bot_class)]
            slots = build_bracket_slots(qualifiers)
            Match.query.filter_by(stage='s2', bot_class=bot_class).delete()
            Match.query.filter_by(stage='s2_placement', bot_class=bot_class).delete()
            pairs = round_pairs_from_slots(slots)
            for i, (a, b) in enumerate(pairs):
                if a is None or b is None:
                    real = a if a is not None else b
                    db.session.add(Match(stage='s2', round_num=1, slot_index=i,
                                          team1_id=real, team2_id=None, bot_class=bot_class, is_bye=True,
                                          winner_id=real, locked=True))
                else:
                    db.session.add(Match(stage='s2', round_num=1, slot_index=i,
                                          team1_id=a, team2_id=b, bot_class=bot_class, locked=False))
            db.session.commit()
            lock_stage2_prereqs(bot_class)
            session[last_key] = 1
        elif action == 'results':
            save_matches = matches_for('s2', round_num, bot_class=bot_class)
            placement_matches = matches_for('s2_placement', bot_class=bot_class)
            for m in save_matches + placement_matches:
                if m.is_bye:
                    continue
                w = request.form.get(f'winner_{m.id}')
                if w:
                    m.winner_id = int(w)
                m.result_type = None
            if len(save_matches) == 1 and all(m.winner_id for m in save_matches):
                for m in save_matches:
                    m.locked = True
            for m in placement_matches:
                if m.winner_id:
                    m.locked = True
            db.session.commit()
            session[f'stage2_last_round_{bot_class}'] = round_num
        elif action == 'generate_next':
            prev = matches_for('s2', round_num, bot_class=bot_class)
            for m in prev:
                m.locked = True
            db.session.commit()
            winners = [m.winner_id for m in prev]
            next_round = round_num + 1
            Match.query.filter_by(stage='s2', round_num=next_round, bot_class=bot_class).delete()
            for i in range(0, len(winners), 2):
                a, b = winners[i], winners[i + 1]
                if a is None or b is None:
                    real = a if a is not None else b
                    db.session.add(Match(stage='s2', round_num=next_round, slot_index=i // 2,
                                          team1_id=real, team2_id=None, bot_class=bot_class, is_bye=True,
                                          winner_id=real, locked=True))
                else:
                    db.session.add(Match(stage='s2', round_num=next_round, slot_index=i // 2,
                                          team1_id=a, team2_id=b, bot_class=bot_class, locked=False))
            if len(prev) == 2:
                losers = []
                for m in prev:
                    if m.winner_id == m.team1_id:
                        losers.append(m.team2_id)
                    elif m.winner_id == m.team2_id:
                        losers.append(m.team1_id)
                if len(losers) == 2 and all(losers):
                    Match.query.filter_by(stage='s2_placement', bot_class=bot_class).delete()
                    db.session.add(Match(stage='s2_placement', round_num=1, slot_index=0,
                                          team1_id=losers[0], team2_id=losers[1], bot_class=bot_class, locked=False))
            db.session.commit()
            session[last_key] = next_round
            return redirect(url_for('stage2', round_num=next_round, **{'class': bot_class}))
        elif action == 'end_tournament':
            for m in matches_for('s2', bot_class=bot_class) + matches_for('s2_placement', bot_class=bot_class):
                m.locked = True
            db.session.commit()
            flash('Tournament ended. All Stage 2 matches are now locked.', 'info')
            return redirect(url_for('stage2', round_num=round_num, **{'class': bot_class}))
        return redirect(url_for('stage2', round_num=round_num, **{'class': bot_class}))

    generated_rounds = [r for r in range(1, 20) if round_generated('s2', r, bot_class)]
    highest_round = generated_rounds[-1] if generated_rounds else None
    remembered = session.get(last_key)
    if not round_generated('s2', round_num, bot_class):
        if remembered and round_generated('s2', remembered, bot_class):
            return redirect(url_for('stage2', round_num=remembered, **{'class': bot_class}))
        if highest_round:
            return redirect(url_for('stage2', round_num=highest_round, **{'class': bot_class}))

    session[last_key] = round_num

    all_rounds = {}
    r = 1
    while round_generated('s2', r, bot_class):
        all_rounds[r] = matches_for('s2', r, bot_class)
        r += 1

    current = matches_for('s2', round_num, bot_class)
    current_generated = bool(current)
    current_locked = round_locked('s2', round_num, bot_class) if current else False
    next_generated = round_generated('s2', round_num + 1, bot_class)
    complete = round_complete('s2', round_num, bot_class) if current else False
    is_final = complete and len(current) == 1
    champion = current[0].winner if is_final else None
    second_place = None
    if is_final:
        final = current[0]
        if final.winner_id == final.team1_id:
            second_place = final.team2
        else:
            second_place = final.team1
    placement_match = stage2_placement_match(bot_class)
    placement_complete = placement_match and placement_match.winner_id is not None
    third_place = placement_match.winner if placement_complete else None

    decider_needed = round_complete('s1_r1', 1, bot_class) and round_complete('s1_r2', 1, bot_class) and len(stage1_buckets(bot_class)[1]) > 0
    decider_done = round_complete('decider', 1, bot_class) if round_generated('decider', 1, bot_class) else (not decider_needed)
    qualifiers_ready = round_complete('s1_r1', 1, bot_class) and round_complete('s1_r2', 1, bot_class) and decider_done

    return render_template('stage2_match.html', all_rounds=all_rounds, current_matches=current,
                           round_num=round_num, current_generated=current_generated,
                           current_locked=current_locked, next_generated=next_generated,
                           complete=complete, is_final=is_final, champion=champion,
                           second_place=second_place, third_place=third_place,
                           placement_match=placement_match, placement_complete=placement_complete,
                           qualifiers_ready=qualifiers_ready,
                           current_class=bot_class, BOT_CLASSES=enabled, CLASS_LABELS=CLASS_LABELS)


# ---------- queue system ----------

@app.route('/queue', methods=['GET', 'POST'])
@login_required
def queue():
    current_class = current_selected_class('3lb')
    enabled = enabled_classes()

    if request.method == 'POST':
        action = request.form.get('action')
        match_id = request.form.get('match_id')
        m = Match.query.get(match_id) if match_id else None

        if action == 'start_match' and m:
            running = Match.query.filter_by(bot_class=current_class, queue_status='in_progress').first()
            if running:
                flash('A match is already in progress. Finish or re-queue it first.', 'error')
            else:
                m.queue_status = 'in_progress'
                db.session.commit()

        elif action == 'requeue_bottom' and m:
            max_order_match = Match.query.filter_by(bot_class=current_class, queue_status='queued')\
                                         .order_by(Match.queue_order.desc()).first()
            next_order = (max_order_match.queue_order + 1) if max_order_match else 0
            
            m.queue_status = 'queued'
            m.queue_order = next_order
            m.winner_id = None
            m.locked = False
            m.result_type = None
            db.session.commit()
            flash(f'Match sent back to the bottom of the upcoming queue.', 'info')

        elif action == 'finish_match' and m:
            m.queue_status = 'awaiting_results'
            db.session.commit()

        elif action == 'auto_fill_queue':
            unassigned = Match.query.filter(
                Match.bot_class == current_class,
                Match.is_bye == False,
                Match.winner_id == None,
                Match.queue_status == 'queued'
            ).order_by(Match.stage, Match.round_num, Match.slot_index).all()

            for idx, match in enumerate(unassigned):
                match.queue_order = idx
            db.session.commit()
            flash('Queue refreshed with upcoming matches.', 'info')

        return redirect(url_for('queue', **{'class': current_class}))

    in_progress = Match.query.filter_by(bot_class=current_class, queue_status='in_progress').first()

    queued_matches = Match.query.filter_by(bot_class=current_class, queue_status='queued', winner_id=None)\
                               .order_by(Match.queue_order.asc()).all()

    awaiting_results = Match.query.filter_by(bot_class=current_class, queue_status='awaiting_results', winner_id=None)\
                                   .order_by(Match.id.desc()).all()

    completed_matches = Match.query.filter(Match.bot_class == current_class, Match.winner_id != None)\
                                   .order_by(Match.id.desc()).all()

    return render_template('queue.html',
                           in_progress=in_progress,
                           queued_matches=queued_matches,
                           awaiting_results=awaiting_results,
                           completed_matches=completed_matches,
                           current_class=current_class,
                           BOT_CLASSES=enabled,
                           CLASS_LABELS=CLASS_LABELS)


@app.route('/api/reorder_queue', methods=['POST'])
@login_required
def reorder_queue():
    order_data = request.json.get('order', [])
    for position, match_id in enumerate(order_data):
        m = Match.query.get(match_id)
        if m:
            m.queue_order = position
    db.session.commit()
    return jsonify({'status': 'success'})


@app.route('/reset', methods=['POST'])
@login_required
def reset_tournament():
    Match.query.delete()
    db.session.commit()
    flash('Tournament has been reset. All match pairings and results have been cleared.', 'info')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)