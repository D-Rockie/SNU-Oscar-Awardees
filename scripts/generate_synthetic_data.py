import os
import csv
from datetime import datetime, timedelta
import random

# Ensure we can import the Flask app
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import app, db, Club


def month_range(months: int = 12):
    today = datetime.utcnow().replace(day=1)
    for i in range(months):
        m = today - timedelta(days=30 * i)
        yield m.year, m.month


def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def write_csv(filepath: str, header: list[str], rows: list[list]):
    ensure_dir(os.path.dirname(filepath))
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def generate_instagram(clubs):
    rows = []
    for club in clubs:
        base_posts = random.randint(2, 15)
        base_likes = random.randint(100, 1500)
        base_reach = random.randint(800, 8000)
        for year, month in month_range(12):
            seasonality = 1.0 + 0.2 * random.uniform(-1, 1)
            posts = max(0, int(random.gauss(base_posts, 3) * seasonality))
            likes = max(0, int(random.gauss(base_likes, 200) * (0.8 + posts / 40)))
            reach = max(0, int(random.gauss(base_reach, 600) * (0.9 + posts / 50)))
            rows.append([club.id, club.name, year, month, posts, likes, reach])
    write_csv('data/instagram_monthly.csv',
              ['club_id', 'club_name', 'year', 'month', 'posts', 'likes', 'reach'],
              rows)


def generate_whatsapp(clubs):
    rows = []
    for club in clubs:
        base_msgs = random.randint(200, 1500)
        sentiment_center = random.uniform(-0.1, 0.6)
        for year, month in month_range(12):
            activity = max(0, int(random.gauss(base_msgs, base_msgs * 0.25)))
            sentiment = max(-1.0, min(1.0, random.gauss(sentiment_center, 0.25)))
            active_members = max(5, int((club.member_count or 30) * random.uniform(0.2, 0.7)))
            rows.append([club.id, club.name, year, month, activity, round(sentiment, 3), active_members])
    write_csv('data/whatsapp_monthly.csv',
              ['club_id', 'club_name', 'year', 'month', 'messages', 'sentiment', 'active_members'],
              rows)


def generate_attendance(clubs):
    rows = []
    for club in clubs:
        base_events = random.randint(1, 5)
        for year, month in month_range(12):
            events = max(0, int(random.gauss(base_events, 1)))
            for e in range(events):
                event_name = f"{club.name} Event {e + 1}"
                attendees = max(5, int(random.gauss((club.member_count or 40) * 0.5, 10)))
                rows.append([club.id, club.name, year, month, event_name, attendees])
    write_csv('data/attendance_events.csv',
              ['club_id', 'club_name', 'year', 'month', 'event_name', 'attendees'],
              rows)


def generate_awards(clubs):
    rows = []
    award_pool = [
        'Hackathon Winner', 'Debate Trophy', 'Cultural Fest Champion', 'Community Service',
        'Innovation Prize', 'Leadership Cup', 'Sports Meet Medal', 'Photography Contest'
    ]
    for club in clubs:
        wins_this_year = max(0, int(random.gauss(1.0 if (club.category or '').lower() in ['technical', 'cultural'] else 0.5, 1)))
        # Distribute wins over months
        months = list(month_range(12))
        random.shuffle(months)
        for i in range(min(wins_this_year, len(months))):
            year, month = months[i]
            award_name = random.choice(award_pool)
            level = random.choice(['College', 'City', 'State', 'National'])
            rows.append([club.id, club.name, year, month, award_name, level])
    write_csv('data/awards_won.csv',
              ['club_id', 'club_name', 'year', 'month', 'award_name', 'level'],
              rows)


def generate_reports(clubs):
    reports_dir = os.path.join('data', 'reports')
    ensure_dir(reports_dir)
    positive_snippets = [
        'successful workshop with high student participation',
        'collaboration with external organization boosted outreach',
        'won first place in inter-college competition',
        'mentorship program improved leadership skills',
        'community service created measurable impact',
        'innovation showcased at tech fest received praise',
        'excellent feedback with high satisfaction scores',
        'record attendance and strong engagement throughout the semester',
    ]
    neutral_snippets = [
        'regular weekly meetings were conducted',
        'events organized as per calendar',
        'participation remained steady',
        'sessions included talks and demonstrations',
    ]
    negative_snippets = [
        'event postponements due to resource constraints',
        'lower turnout than expected for some sessions',
        'sponsorship challenges affected event scale',
        'schedule conflicts impacted participation',
    ]
    for club in clubs:
        positives = random.randint(6, 12)
        neutrals = random.randint(3, 6)
        negatives = random.randint(0, 3)
        lines = [
            f"Club: {club.name}",
            f"Category: {club.category}",
            f"Year: {datetime.utcnow().year}",
            "Summary Report:",
            ""
        ]
        lines += [f"- {random.choice(positive_snippets)}." for _ in range(positives)]
        lines += [f"- {random.choice(neutral_snippets)}." for _ in range(neutrals)]
        lines += [f"- {random.choice(negative_snippets)}." for _ in range(negatives)]
        with open(os.path.join(reports_dir, f"club_{club.id}.txt"), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))


def main():
    with app.app_context():
        db.create_all()
        clubs = Club.query.all()
        if not clubs:
            raise SystemExit('No clubs found. Run the app once to seed clubs, or add clubs first.')
        generate_instagram(clubs)
        generate_whatsapp(clubs)
        generate_attendance(clubs)
        generate_awards(clubs)
        generate_reports(clubs)
        print('Synthetic datasets written under data/')


if __name__ == '__main__':
    main()


