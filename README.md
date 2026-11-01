# Bracket App

Bracketing and Queueing System for Railside Rumble Competition

Uses Neon Postgres Database

Deployed on Render

To ensure website remains active and doesn't spin down after 15 minutes of activity this uses uptime robot to ping the website every 5 minutes.

Start by adding teams. Use the Bulk Add Format Generator Template if its helpful

For streaming, open the Stage 2 bracket's **Streaming Overlay** link or use `/stage2/overlay?class=3lb` as a transparent browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. The overlay refreshes every 20 seconds.

The upcoming match queue also has a standalone **Streaming Overlay** link on the queue control page, or use `/queue/overlay?class=3lb` as a browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. It refreshes every 20 seconds.

The group standings page also has a **Streaming Overlay** link, or use `/standings/overlay?class=3lb` as a browser source. Replace `3lb` with `1lb` or `1lb_plant` to select another bot class. It refreshes every 10 seconds.
