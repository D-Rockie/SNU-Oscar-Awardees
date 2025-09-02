import os
import csv
from collections import defaultdict

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import app, db, Club, ClubMetrics


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')


def read_csv(path):
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def aggregate_instagram(rows, agg):
    for r in rows:
        cid = int(r['club_id'])
        agg[cid]['instagram_posts'] += int(r['posts'])
        agg[cid]['instagram_likes'] += int(r['likes'])
        agg[cid]['instagram_reach'] += int(r['reach'])


def aggregate_whatsapp(rows, agg):
    for r in rows:
        cid = int(r['club_id'])
        agg[cid]['whatsapp_messages'] += int(r['messages'])
        agg[cid]['_sent_sum'] += float(r['sentiment'])
        agg[cid]['_sent_cnt'] += 1


def aggregate_attendance(rows, agg):
    for r in rows:
        cid = int(r['club_id'])
        agg[cid]['offline_attendance'] += int(r['attendees'])


def aggregate_awards(rows, agg):
    for r in rows:
        cid = int(r['club_id'])
        agg[cid]['awards_won'] += 1


def main():
    paths = {
        'instagram': os.path.join(DATA_DIR, 'instagram_monthly.csv'),
        'whatsapp': os.path.join(DATA_DIR, 'whatsapp_monthly.csv'),
        'attendance': os.path.join(DATA_DIR, 'attendance_events.csv'),
        'awards': os.path.join(DATA_DIR, 'awards_won.csv'),
    }

    missing = [k for k, p in paths.items() if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"Missing datasets: {', '.join(missing)}. Generate them first.")

    with app.app_context():
        clubs = {c.id: c for c in Club.query.all()}
        if not clubs:
            raise SystemExit('No clubs found in DB.')

        agg = defaultdict(lambda: defaultdict(int))
        for cid in clubs.keys():
            agg[cid]['_sent_sum'] = 0.0
            agg[cid]['_sent_cnt'] = 0

        aggregate_instagram(read_csv(paths['instagram']), agg)
        aggregate_whatsapp(read_csv(paths['whatsapp']), agg)
        aggregate_attendance(read_csv(paths['attendance']), agg)
        aggregate_awards(read_csv(paths['awards']), agg)

        # Upsert ClubMetrics
        for cid, metrics in agg.items():
            cm = ClubMetrics.query.filter_by(club_id=cid).first()
            if not cm:
                cm = ClubMetrics(club_id=cid)
                db.session.add(cm)
            cm.instagram_posts = int(metrics.get('instagram_posts', 0))
            cm.instagram_likes = int(metrics.get('instagram_likes', 0))
            cm.instagram_reach = int(metrics.get('instagram_reach', 0))
            cm.whatsapp_messages = int(metrics.get('whatsapp_messages', 0))
            sent_sum = float(metrics.get('_sent_sum', 0.0))
            sent_cnt = int(metrics.get('_sent_cnt', 0))
            cm.whatsapp_sentiment = (sent_sum / sent_cnt) if sent_cnt > 0 else 0.0
            cm.awards_won = int(metrics.get('awards_won', 0))
            cm.offline_attendance = int(metrics.get('offline_attendance', 0))

        db.session.commit()
        print('ClubMetrics updated from CSV datasets.')


if __name__ == '__main__':
    main()


