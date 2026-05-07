FROM docker.io/alpine:3.20

RUN apk add --no-cache bash openssh-server python3 py3-pip rsync shadow tzdata ffmpeg nodejs \
  && mkdir -p /repository /root/.ssh /run/sshd /app /app/data \
  && chmod 700 /root/.ssh

COPY requirements.txt /app/
RUN python3 -m venv /app/venv \
  && /app/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

EXPOSE 22 80

CMD ["/usr/local/bin/start.sh"]
