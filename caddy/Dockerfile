FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY ../frontend/index.html /srv/www/index.html
RUN mkdir -p /var/log/caddy
