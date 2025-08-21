FROM python:3.12-bullseye

WORKDIR /personal_project
COPY . ./

# --- 先安裝 Microsoft ODBC Driver for SQL Server (必須 root 權限) ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gnupg \
        ca-certificates \
        curl \
        unixodbc-dev && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/11/prod bullseye main" \
        > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- 建立非 root 使用者 ---
RUN groupadd eng && \
    useradd -m -g eng eng && \
    chown eng:eng /personal_project

# 切換成 eng 使用者
USER eng
ENV PATH=/home/eng/.local/bin:$PATH

# Python 相關設定
ENV TZ=Asia/Taipei \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir -r requirements.txt gunicorn

CMD gunicorn app:app -b :${PORT:-8080} --workers ${WORKERS:-1} --threads ${THREADS:-1}