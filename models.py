from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    assigned_team_name = db.Column(db.String(80), nullable=False, default='')
    bot_class = db.Column(db.String(20), nullable=False, default='3lb')
    checked_in = db.Column(db.Boolean, default=False)
    safety_waiver = db.Column(db.Boolean, default=False)
    registration_fee = db.Column(db.Boolean, default=False)
    pit_table_number = db.Column(db.String(20), nullable=True)
    dropped = db.Column(db.Boolean, default=False)
    
    # 20-Minute Rest Timer Fields
    last_match_end_time = db.Column(db.DateTime, nullable=True)
    extension_used = db.Column(db.Boolean, default=False)

    @property
    def display_name(self):
        return f"{self.name} ({self.assigned_team_name})" if self.assigned_team_name else self.name

    def __repr__(self):
        return f"<Bot {self.name} ({self.bot_class}) -> {self.assigned_team_name}>"


# stage values: 's1_r1', 's1_r2', 'decider', 's2', 's2_placement'
class Match(db.Model):
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    stage = db.Column(db.String(20), nullable=False)
    round_num = db.Column(db.Integer, default=1)
    slot_index = db.Column(db.Integer, default=0)
    bot_class = db.Column(db.String(20), nullable=False, default='3lb')

    team1_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    team2_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    is_bye = db.Column(db.Boolean, default=False)

    locked = db.Column(db.Boolean, default=False)
    result_type = db.Column(db.String(10), nullable=True)

    # Queue Management Fields
    queue_status = db.Column(db.String(20), default='queued')
    queue_order = db.Column(db.Integer, default=0)

    team1 = db.relationship('Team', foreign_keys=[team1_id])
    team2 = db.relationship('Team', foreign_keys=[team2_id])
    winner = db.relationship('Team', foreign_keys=[winner_id])


class TournamentSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<TournamentSetting {self.key}={self.enabled}>"