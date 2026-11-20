# Bracket App

Bracketing and Queueing System for Railside Rumble Competition

Uses Neon Postgres Database

Deployed on Render

To ensure website remains active and doesn't spin down after 15 minutes of activity this uses uptime robot to ping the website every 5 minutes.

Start by adding teams. Use the Bulk Add Format Generator Template if its helpful

For streaming, open the Stage 2 bracket's **Streaming Overlay** link or use `/stage2/overlay?class=3lb` as a transparent browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. The overlay refreshes every 20 seconds.

The upcoming match queue also has a standalone **Streaming Overlay** link on the queue control page, or use `/queue/overlay?class=3lb` as a browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. It refreshes every 20 seconds.

The group standings page also has a **Streaming Overlay** link, or use `/standings/overlay?class=3lb` as a browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. It refreshes every 10 seconds.

## Running locally

1. Install Python 3.10+ and the dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in `SECRET_KEY` and `APP_PASSWORD` (the admin login password). Leave `DATABASE_URL` out to use a local SQLite file (`bracket.db`, ignored by git).
3. Run `python app.py` and open http://localhost:5000. Log in with `APP_PASSWORD` for the admin pages.

On Render, set the same variables in the service's Environment tab (with `DATABASE_URL` pointing at Neon) and start it with `gunicorn app:app`. Keep it to one gunicorn worker (gunicorn's default): the page cache lives in memory, so extra workers would show each other's stale pages.

## Testing and troubleshooting locally

Everything above runs on your own computer with a throwaway `bracket.db`, so you can break things freely without touching the real tournament data.

`seed_demo.py` fills that local database with demo bots and can play rounds with random winners, so you can jump straight to the part you're troubleshooting:

```
python seed_demo.py --fresh                 # start over with 12 demo bots in 3lb
python seed_demo.py --fresh --play stage1   # ...and play Rounds 1, 2 and the decider
python seed_demo.py --fresh --play all      # ...all the way to a champion
python seed_demo.py --bots 6 --class 1lb    # add 6 bots to another class
```

Run it, then start `python app.py` and look around. It refuses to run if `DATABASE_URL` points at a real database. Run `python seed_demo.py -h` for all options.

To test with two devices (e.g. a phone as the queue screen), run `flask --app app run --host 0.0.0.0` and open `http://<this computer's IP>:5000` on the other device (same Wi-Fi).

To start over, delete `bracket.db` (or use `--fresh`).
