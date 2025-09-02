from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import csv
from collections import defaultdict
from datetime import datetime
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///awards.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))  # e.g., 'Academic', 'Cultural', 'Technical'
    founded_year = db.Column(db.Integer)
    member_count = db.Column(db.Integer)
    achievements = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Award(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))  # e.g., 'Best Public Speaking', 'Best Technical Club'
    criteria = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    winners_declared = db.Column(db.Boolean, default=False)
    declared_at = db.Column(db.DateTime)

class Nomination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    award_id = db.Column(db.Integer, db.ForeignKey('award.id'), nullable=False)
    reason = db.Column(db.Text)
    submitted_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_approved = db.Column(db.Boolean, default=False)
    
    club = db.relationship('Club', backref='nominations')
    award = db.relationship('Award', backref='nominations')

class ClubMetrics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), unique=True, nullable=False)
    instagram_posts = db.Column(db.Integer, default=0)
    instagram_likes = db.Column(db.Integer, default=0)
    instagram_reach = db.Column(db.Integer, default=0)
    whatsapp_messages = db.Column(db.Integer, default=0)
    whatsapp_sentiment = db.Column(db.Float, default=0.0)  # -1 to 1 synthetic
    awards_won = db.Column(db.Integer, default=0)
    offline_attendance = db.Column(db.Integer, default=0)

    club = db.relationship('Club', backref=db.backref('metrics', uselist=False))

class EvaluationWeights(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Global single row config
    w_social = db.Column(db.Float, default=0.30)  # posts/likes/reach composite
    w_whatsapp = db.Column(db.Float, default=0.20)  # messages & sentiment
    w_awards = db.Column(db.Float, default=0.20)  # awards won
    w_feedback = db.Column(db.Float, default=0.15)  # student votes
    w_attendance = db.Column(db.Float, default=0.15)  # offline attendance
    w_reports = db.Column(db.Float, default=0.10)  # textual report impact

class FeedbackVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    award_id = db.Column(db.Integer, db.ForeignKey('award.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    voter_hash = db.Column(db.String(120), nullable=True)  # simple duplicate prevention token
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    award = db.relationship('Award', backref='votes')
    club = db.relationship('Club', backref='votes')

class AwardDecision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    award_id = db.Column(db.Integer, db.ForeignKey('award.id'), unique=True, nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    reason = db.Column(db.Text)
    decided_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    decided_at = db.Column(db.DateTime, default=datetime.utcnow)

    award = db.relationship('Award', backref=db.backref('decision', uselist=False))
    club = db.relationship('Club')
    decider = db.relationship('User')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------- Lightweight SQLite migration helpers --------

def ensure_award_columns():
    try:
        info_award = db.session.execute(db.text("PRAGMA table_info('award')")).all()
        cols_award = {row[1] for row in info_award}
        if 'winners_declared' not in cols_award:
            db.session.execute(db.text("ALTER TABLE award ADD COLUMN winners_declared BOOLEAN DEFAULT 0"))
        if 'declared_at' not in cols_award:
            db.session.execute(db.text("ALTER TABLE award ADD COLUMN declared_at DATETIME"))
        # ensure AwardDecision table exists
        db.session.execute(db.text("CREATE TABLE IF NOT EXISTS award_decision (id INTEGER PRIMARY KEY AUTOINCREMENT, award_id INTEGER UNIQUE, club_id INTEGER, reason TEXT, decided_by INTEGER, decided_at DATETIME)"))
        # ensure ClubMetrics new column
        info_metrics = db.session.execute(db.text("PRAGMA table_info('club_metrics')")).all()
        cols_metrics = {row[1] for row in info_metrics}
        if 'offline_attendance' not in cols_metrics:
            db.session.execute(db.text("ALTER TABLE club_metrics ADD COLUMN offline_attendance INTEGER DEFAULT 0"))
        # ensure EvaluationWeights new column
        info_weights = db.session.execute(db.text("PRAGMA table_info('evaluation_weights')")).all()
        cols_weights = {row[1] for row in info_weights}
        if 'w_attendance' not in cols_weights:
            db.session.execute(db.text("ALTER TABLE evaluation_weights ADD COLUMN w_attendance FLOAT DEFAULT 0.15"))
        if 'w_reports' not in cols_weights:
            db.session.execute(db.text("ALTER TABLE evaluation_weights ADD COLUMN w_reports FLOAT DEFAULT 0.10"))
        # Backfill NULL weights for existing single row
        db.session.execute(db.text("UPDATE evaluation_weights SET w_attendance = COALESCE(w_attendance, 0.15)"))
        db.session.execute(db.text("UPDATE evaluation_weights SET w_reports = COALESCE(w_reports, 0.10)"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

# -------- Automated eligibility rules and helpers --------

def _text(s: str) -> str:
    return (s or '').lower()

def get_award_eligibility_predicate(award_name: str):
    name = award_name.lower()

    overrides = {
        'best technical club': ['mun club'],
    }

    if 'public speaking' in name:
        def pred(club: Club) -> bool:
            cn = _text(club.name)
            cd = _text(club.description)
            return (
                'debate' in cn or 'toastmasters' in cn or 'mun' in cn or
                'debate' in cd or 'public speaking' in cd or 'oratory' in cd
            )
        return pred

    if 'technical' in name:
        def pred(club: Club) -> bool:
            cn = _text(club.name)
            cd = _text(club.description)
            forced = any(sub in cn for sub in overrides.get('best technical club', []))
            return forced or (
                'coding' in cn or 'robotics' in cn or 'ai' in cn or 'ml' in cn or 'machine learning' in cd or
                club.category == 'Technical' or 'programming' in cd or 'software' in cd or 'hackathon' in cd
            )
        return pred

    if 'cultural' in name:
        def pred(club: Club) -> bool:
            cn = _text(club.name)
            cd = _text(club.description)
            return (
                club.category == 'Cultural' or 'dance' in cn or 'music' in cn or 'photography' in cn or
                'dance' in cd or 'music' in cd or 'arts' in cd or 'culture' in cd
            )
        return pred

    if 'most active' in name:
        def pred(club: Club) -> bool:
            return (club.member_count or 0) >= 40
        return pred

    if 'best new club' in name or ('new club' in name):
        def pred(club: Club) -> bool:
            return (club.founded_year or 0) >= (datetime.utcnow().year - 2)
        return pred

    if 'community impact' in name:
        def pred(club: Club) -> bool:
            cd = _text(club.description) + ' ' + _text(club.achievements)
            return ('community' in cd) or ('service' in cd) or ('impact' in cd) or ('outreach' in cd)
        return pred

    if 'innovation' in name:
        def pred(club: Club) -> bool:
            cd = _text(club.description) + ' ' + _text(club.achievements)
            return ('innov' in cd) or ('ai' in cd) or ('robot' in cd) or ('ml' in cd) or ('new' in cd)
        return pred

    if 'leadership' in name:
        def pred(club: Club) -> bool:
            cd = _text(club.description) + ' ' + _text(club.achievements)
            return ('leader' in cd) or ('organizer' in cd) or ('management' in cd)
        return pred

    return lambda club: True


def auto_nominate_all_awards():
    awards = Award.query.all()
    clubs = Club.query.all()
    for award in awards:
        predicate = get_award_eligibility_predicate(award.name)
        for club in clubs:
            if predicate(club):
                exists = Nomination.query.filter_by(club_id=club.id, award_id=award.id).first()
                if exists:
                    continue
                reason = f"Auto-nominated based on eligibility: '{award.name}' criteria matched by {club.name}."
                nomination = Nomination(
                    club_id=club.id,
                    award_id=award.id,
                    reason=reason,
                    submitted_by=None,
                    is_approved=True  # accept automatically
                )
                db.session.add(nomination)
    db.session.commit()

# -------- Scoring helpers --------

def get_weights() -> EvaluationWeights:
    weights = EvaluationWeights.query.first()
    if not weights:
        weights = EvaluationWeights()
        db.session.add(weights)
        db.session.commit()
    return weights


def normalize(values):
    values = list(values)
    if not values:
        return []
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        return [0.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _load_synthetic_metrics():
    base_dir = os.path.join(os.path.dirname(__file__), 'data')
    paths = {
        'instagram': os.path.join(base_dir, 'instagram_monthly.csv'),
        'whatsapp': os.path.join(base_dir, 'whatsapp_monthly.csv'),
        'attendance': os.path.join(base_dir, 'attendance_events.csv'),
        'awards': os.path.join(base_dir, 'awards_won.csv'),
    }
    agg = defaultdict(lambda: {
        'instagram_posts': 0,
        'instagram_likes': 0,
        'instagram_reach': 0,
        'whatsapp_messages': 0,
        'whatsapp_sentiment_sum': 0.0,
        'whatsapp_sentiment_cnt': 0,
        'awards_won': 0,
        'offline_attendance': 0,
        'report_score_sum': 0.0,
        'report_score_cnt': 0,
    })

    def _read(path):
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    for r in _read(paths['instagram']):
        cid = int(r['club_id'])
        agg[cid]['instagram_posts'] += int(r['posts'])
        agg[cid]['instagram_likes'] += int(r['likes'])
        agg[cid]['instagram_reach'] += int(r['reach'])

    for r in _read(paths['whatsapp']):
        cid = int(r['club_id'])
        agg[cid]['whatsapp_messages'] += int(r['messages'])
        agg[cid]['whatsapp_sentiment_sum'] += float(r['sentiment'])
        agg[cid]['whatsapp_sentiment_cnt'] += 1

    for r in _read(paths['attendance']):
        cid = int(r['club_id'])
        agg[cid]['offline_attendance'] += int(r['attendees'])

    for r in _read(paths['awards']):
        cid = int(r['club_id'])
        agg[cid]['awards_won'] += 1

    # parse textual reports (simple heuristic scoring)
    reports_dir = os.path.join(base_dir, 'reports')
    if os.path.isdir(reports_dir):
        positive_keywords = [
            'successful', 'collaboration', 'won', 'first place', 'mentorship', 'improved', 'impact',
            'innovation', 'praise', 'excellent', 'record attendance', 'strong engagement', 'high satisfaction'
        ]
        negative_keywords = [
            'postponements', 'lower turnout', 'challenges', 'conflicts', 'cancelled', 'delay'
        ]
        for club in Club.query.all():
            path = os.path.join(reports_dir, f'club_{club.id}.txt')
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read().lower()
                pos = sum(text.count(k) for k in positive_keywords)
                neg = sum(text.count(k) for k in negative_keywords)
                score = max(0.0, min(1.0, (pos - 0.5 * neg) / 10.0))
                agg[club.id]['report_score_sum'] += score
                agg[club.id]['report_score_cnt'] += 1
            except Exception:
                continue

    # finalize sentiment average
    finalized = {}
    for cid, m in agg.items():
        cnt = m['whatsapp_sentiment_cnt']
        avg_s = (m['whatsapp_sentiment_sum'] / cnt) if cnt > 0 else 0.0
        finalized[cid] = {
            'instagram_posts': m['instagram_posts'],
            'instagram_likes': m['instagram_likes'],
            'instagram_reach': m['instagram_reach'],
            'whatsapp_messages': m['whatsapp_messages'],
            'whatsapp_sentiment': avg_s,
            'awards_won': m['awards_won'],
            'offline_attendance': m['offline_attendance'],
            'report_score': (m['report_score_sum'] / m['report_score_cnt']) if m['report_score_cnt'] > 0 else 0.0,
        }
    return finalized


def compute_rankings_for_award(award: Award):
    predicate = get_award_eligibility_predicate(award.name)
    eligible = [c for c in Club.query.all() if predicate(c)]
    if not eligible:
        return []

    synth = _load_synthetic_metrics()
    vote_counts = {c.id: FeedbackVote.query.filter_by(award_id=award.id, club_id=c.id).count() for c in eligible}

    posts = [synth.get(c.id, {}).get('instagram_posts', 0) for c in eligible]
    likes = [synth.get(c.id, {}).get('instagram_likes', 0) for c in eligible]
    reach = [synth.get(c.id, {}).get('instagram_reach', 0) for c in eligible]
    msgs = [synth.get(c.id, {}).get('whatsapp_messages', 0) for c in eligible]
    senti = [synth.get(c.id, {}).get('whatsapp_sentiment', 0) for c in eligible]
    awards_won = [synth.get(c.id, {}).get('awards_won', 0) for c in eligible]
    votes = [vote_counts[c.id] for c in eligible]
    attend = [synth.get(c.id, {}).get('offline_attendance', 0) for c in eligible]

    n_posts = normalize(posts)
    n_likes = normalize(likes)
    n_reach = normalize(reach)
    n_msgs = normalize(msgs)
    n_senti = normalize(senti)
    n_awards = normalize(awards_won)
    n_votes = normalize(votes)
    n_attend = normalize(attend)
    n_reports = normalize([synth.get(c.id, {}).get('report_score', 0) for c in eligible])

    weights = get_weights()
    results = []
    for idx, club in enumerate(eligible):
        social = (n_posts[idx] + n_likes[idx] + n_reach[idx]) / 3.0
        whatsapp = (n_msgs[idx] * 0.7) + (n_senti[idx] * 0.3)
        awards_component = n_awards[idx]
        feedback_component = n_votes[idx]
        attendance_component = n_attend[idx]
        reports_component = n_reports[idx]
        score = (
            weights.w_social * social +
            weights.w_whatsapp * whatsapp +
            weights.w_awards * awards_component +
            weights.w_feedback * feedback_component +
            weights.w_attendance * attendance_component +
            weights.w_reports * reports_component
        )
        results.append({
            'club': club,
            'score': round(score, 4),
            'details': {
                'social': round(social, 4),
                'whatsapp': round(whatsapp, 4),
                'awards': round(awards_component, 4),
                'feedback': round(feedback_component, 4),
                'attendance': round(attendance_component, 4),
                'reports': round(reports_component, 4),
                'raw': {
                    'posts': posts[idx], 'likes': likes[idx], 'reach': reach[idx],
                    'messages': msgs[idx], 'sentiment': senti[idx], 'awards_won': awards_won[idx],
                    'votes': votes[idx], 'offline_attendance': attend[idx], 'report_score': synth.get(club.id, {}).get('report_score', 0)
                }
            }
        })

    results.sort(key=lambda r: r['score'], reverse=True)
    for i, r in enumerate(results, start=1):
        r['rank'] = i
    return results

# Routes
@app.route('/')
def index():
    return redirect(url_for('awards'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form.get('role', 'student')
        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password', 'error')
            return render_template('login.html', current_role=role)

        # Enforce selected role
        if role == 'admin' and not user.is_admin:
            flash('You do not have admin access. Choose Student or contact admin.', 'error')
            return render_template('login.html', current_role=role)
        if role == 'student' and user.is_admin:
            flash('You selected Student but this is an admin account. Choose Admin.', 'error')
            return render_template('login.html', current_role=role)

        login_user(user)
        flash('Login successful!', 'success')
        return redirect(url_for('admin_dashboard' if user.is_admin else 'dashboard'))

    # GET
    role = request.args.get('role', 'student')
    return render_template('login.html', current_role=role)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # Use unified login with admin role preselected
    if request.method == 'POST':
        return redirect(url_for('login') + '?role=admin')
    return redirect(url_for('login', role='admin'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    # Declared winners for students to see on their home page
    winners = (
        AwardDecision.query
        .join(Award, AwardDecision.award_id == Award.id)
        .filter(Award.winners_declared == True)
        .all()
    )
    user_nominations = Nomination.query.filter_by(submitted_by=current_user.id).all()
    return render_template('dashboard.html', nominations=user_nominations, winners=winners)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))
    
    clubs = Club.query.all()
    awards = Award.query.all()
    nominations = Nomination.query.all()
    
    return render_template('admin_dashboard.html', 
                         clubs=clubs, 
                         awards=awards, 
                         nominations=nominations)

@app.route('/clubs')
def clubs():
    clubs = Club.query.all()
    return render_template('clubs.html', clubs=clubs)

@app.route('/awards')
def awards():
    awards = Award.query.all()
    return render_template('awards.html', awards=awards)

@app.route('/awards/<int:award_id>')
def award_detail(award_id: int):
    award = Award.query.get_or_404(award_id)
    predicate = get_award_eligibility_predicate(award.name)
    clubs = Club.query.all()
    eligible_clubs = [club for club in clubs if predicate(club)]

    for club in eligible_clubs:
        exists = Nomination.query.filter_by(club_id=club.id, award_id=award.id).first()
        if not exists:
            reason = f"Auto-nominated based on eligibility for '{award.name}'."
            db.session.add(Nomination(club_id=club.id, award_id=award.id, reason=reason))
    db.session.commit()

    nominations = Nomination.query.filter_by(award_id=award.id).all()
    club_id_to_nom = {n.club_id: n for n in nominations}

    return render_template('award_detail.html', award=award, eligible_clubs=eligible_clubs, club_id_to_nom=club_id_to_nom)

# Restore nominate route
@app.route('/nominate', methods=['GET', 'POST'])
@login_required
def nominate():
    if request.method == 'POST':
        club_id = request.form['club_id']
        award_id = request.form['award_id']
        reason = request.form['reason']
        existing = Nomination.query.filter_by(club_id=club_id, award_id=award_id).first()
        if existing:
            flash('Nomination already exists and is accepted.', 'info')
        else:
            db.session.add(Nomination(club_id=club_id, award_id=award_id, reason=reason, submitted_by=current_user.id, is_approved=True))
            db.session.commit()
            flash('Nomination accepted.', 'success')
            return redirect(url_for('dashboard'))
    clubs = Club.query.all()
    awards = Award.query.all()
    return render_template('nominate.html', clubs=clubs, awards=awards)

@app.route('/awards/<int:award_id>/vote', methods=['GET', 'POST'])
@login_required
def vote_award(award_id: int):
    award = Award.query.get_or_404(award_id)
    predicate = get_award_eligibility_predicate(award.name)
    eligible = [c for c in Club.query.all() if predicate(c)]

    if request.method == 'POST':
        club_id = int(request.form['club_id'])
        voter_hash = request.form.get('voter_hash') or None
        if voter_hash and FeedbackVote.query.filter_by(award_id=award.id, voter_hash=voter_hash).first():
            flash('You have already voted for this award.', 'error')
            return redirect(url_for('vote_award', award_id=award.id))
        if club_id not in [c.id for c in eligible]:
            flash('Invalid selection.', 'error')
            return redirect(url_for('vote_award', award_id=award.id))
        vote = FeedbackVote(award_id=award.id, club_id=club_id, voter_hash=voter_hash)
        db.session.add(vote)
        db.session.commit()
        flash('Thanks for your feedback!', 'success')
        return redirect(url_for('awards'))

    rankings = compute_rankings_for_award(award) if (current_user.is_authenticated and current_user.is_admin) else None
    return render_template('vote_award.html', award=award, eligible_clubs=eligible, rankings=rankings)

@app.route('/admin/awards/<int:award_id>/rankings')
@login_required
def admin_award_rankings(award_id: int):
    if not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('awards'))
    award = Award.query.get_or_404(award_id)
    rankings = compute_rankings_for_award(award)
    weights = get_weights()
    decision = AwardDecision.query.filter_by(award_id=award.id).first()
    # Raw vote counts per eligible club
    vote_counts = {}
    predicate = get_award_eligibility_predicate(award.name)
    eligible = [c for c in Club.query.all() if predicate(c)]
    for c in eligible:
        vote_counts[c.id] = FeedbackVote.query.filter_by(award_id=award.id, club_id=c.id).count()
    total_votes = sum(vote_counts.values())
    return render_template('admin_rankings.html', award=award, rankings=rankings, weights=weights, decision=decision, vote_counts=vote_counts, total_votes=total_votes)

@app.route('/admin/awards/<int:award_id>/decide', methods=['POST'])
@login_required
def decide_award(award_id: int):
    if not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('awards'))
    award = Award.query.get_or_404(award_id)
    club_id = int(request.form['club_id'])
    reason = request.form.get('reason', '')
    # Upsert decision
    decision = AwardDecision.query.filter_by(award_id=award.id).first()
    if not decision:
        decision = AwardDecision(award_id=award.id, club_id=club_id, reason=reason, decided_by=current_user.id)
        db.session.add(decision)
    else:
        decision.club_id = club_id
        decision.reason = reason
        decision.decided_by = current_user.id
        decision.decided_at = datetime.utcnow()
    # mark winners declared
    award.winners_declared = True
    award.declared_at = datetime.utcnow()
    db.session.commit()
    flash('Winner set for this award.', 'success')
    return redirect(url_for('admin_award_rankings', award_id=award.id))


@app.route('/admin/approve_nomination/<int:nomination_id>')
@login_required
def approve_nomination(nomination_id: int):
    if not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('awards'))
    nomination = Nomination.query.get_or_404(nomination_id)
    nomination.is_approved = True
    db.session.commit()
    flash('Nomination approved.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject_nomination/<int:nomination_id>')
@login_required
def reject_nomination(nomination_id: int):
    if not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('awards'))
    nomination = Nomination.query.get_or_404(nomination_id)
    db.session.delete(nomination)
    db.session.commit()
    flash('Nomination rejected and removed.', 'success')
    return redirect(url_for('admin_dashboard'))

# Results: show declared winners only
@app.route('/results')
def results():
    decisions = (
        AwardDecision.query
        .join(Award, AwardDecision.award_id == Award.id)
        .filter(Award.winners_declared == True)
        .order_by(Award.category, Award.name)
        .all()
    )
    return render_template('results.html', decisions=decisions)

# ---- Seeding synthetic metrics ----
def seed_synthetic_metrics():
    clubs = Club.query.all()
    for club in clubs:
        if club.metrics:
            continue
        db.session.add(ClubMetrics(
            club_id=club.id,
            instagram_posts=random.randint(5, 120),
            instagram_likes=random.randint(200, 12000),
            instagram_reach=random.randint(1000, 80000),
            whatsapp_messages=random.randint(300, 8000),
            whatsapp_sentiment=round(random.uniform(-0.2, 0.9), 2),
            awards_won=random.randint(0, 20),
            offline_attendance=random.randint(100, 5000)
        ))
    if not EvaluationWeights.query.first():
        db.session.add(EvaluationWeights(w_social=0.30, w_whatsapp=0.20, w_awards=0.20, w_feedback=0.15, w_attendance=0.15))
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Ensure new columns/tables exist when upgrading existing DBs
        ensure_award_columns()
        
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
        
        if Club.query.count() == 0:
            sample_clubs = [
                Club(name='MUN Club', description='Model United Nations Club focused on diplomacy, public speaking and global issues.', category='Academic', founded_year=2020, member_count=45),
                Club(name='Debate Club', description='Competitive Debate Team with strong oratory skills and tournaments.', category='Academic', founded_year=2019, member_count=38),
                Club(name='Toastmasters Club', description='Public Speaking and Leadership Development through regular speeches and evaluations.', category='Academic', founded_year=2021, member_count=52),
                Club(name='Coding Club', description='Programming and Software Development; hosts hackathons and coding challenges.', category='Technical', founded_year=2018, member_count=65),
                Club(name='Robotics Club', description='Robotics and Automation projects; participates in innovation contests.', category='Technical', founded_year=2020, member_count=42),
                Club(name='AI/ML Club', description='Artificial Intelligence and Machine Learning research and projects.', category='Technical', founded_year=2022, member_count=35),
                Club(name='Dance Club', description='Contemporary and Classical Dance; cultural performances and arts.', category='Cultural', founded_year=2019, member_count=58),
                Club(name='Music Club', description='Instrumental and Vocal Music; concerts and cultural events.', category='Cultural', founded_year=2018, member_count=47),
                Club(name='Photography Club', description='Digital and Film Photography; arts and cultural exhibitions.', category='Cultural', founded_year=2021, member_count=33),
                Club(name='Sports Club', description='Various Sports Activities with regular practice and events.', category='Sports', founded_year=2017, member_count=72),
                Club(name='Chess Club', description='Strategic Board Games; tournaments and analytical thinking.', category='Academic', founded_year=2020, member_count=28),
                Club(name='Literature Club', description='Creative Writing and Poetry; leadership in literary events.', category='Cultural', founded_year=2019, member_count=31)
            ]
            db.session.add_all(sample_clubs)
            db.session.commit()
        
        if Award.query.count() == 0:
            sample_awards = [
                Award(name='Best Public Speaking Club', description='Excellence in public speaking and communication', category='Communication', criteria='Demonstrated excellence in public speaking, debate, and communication skills'),
                Award(name='Best Technical Club', description='Outstanding achievements in technology and innovation', category='Technical', criteria='Innovation in technology projects, hackathons, and technical workshops'),
                Award(name='Best Cultural Club', description='Excellence in promoting arts and culture', category='Cultural', criteria='Cultural events, performances, and community engagement'),
                Award(name='Most Active Club', description='Highest level of engagement and participation', category='General', criteria='Regular meetings, events, and member participation'),
                Award(name='Best New Club', description='Outstanding performance by newly established clubs', category='General', criteria='Clubs founded within the last 2 years with exceptional growth'),
                Award(name='Community Impact Award', description='Significant contribution to the community', category='Service', criteria='Community service projects and social impact initiatives'),
                Award(name='Innovation Award', description='Creative and innovative approaches to club activities', category='Innovation', criteria='Unique projects, creative solutions, and innovative approaches'),
                Award(name='Leadership Excellence', description='Outstanding leadership and organizational skills', category='Leadership', criteria='Effective leadership, team management, and organizational success')
            ]
            db.session.add_all(sample_awards)
            db.session.commit()

        auto_nominate_all_awards()
        seed_synthetic_metrics()
    
    app.run(debug=True)
