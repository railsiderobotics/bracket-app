from app import app
from models import db, Match

with app.app_context():
    q = Match.query.filter(Match.stage.in_(['s2', 's2_placement']))
    updated = q.update({'result_type': None}, synchronize_session=False)
    db.session.commit()
    print(f"Cleared result_type on {updated} Stage 2 matches.")
