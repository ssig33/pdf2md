FROM python:3.11-slim

WORKDIR /app

# システムパッケージの更新とPDF処理に必要なライブラリをインストール
RUN apt-get update && apt-get install -y \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python依存関係をコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY pdf2md.py .

# 実行権限を付与
RUN chmod +x pdf2md.py

# 作業ディレクトリをマウントポイントに設定
WORKDIR /workspace

# デフォルトのエントリーポイント
ENTRYPOINT ["python", "/app/pdf2md.py"]