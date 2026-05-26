# KHU Sandan RAG Q&A System

경희대학교 연구처/산학협력단 게시판 첨부자료를 수집하고, OpenAI + RAG로 질의응답 및 원본 파일 다운로드를 제공하는 Streamlit 시스템입니다.

이 버전은 기존 Supabase Storage 의존도를 낮추기 위해 **Cloudflare R2 + LanceDB/Qdrant** 구조를 지원합니다.

## 1. Recommended architecture

```text
게시판 PDF/HWP/PPT/ZIP 원본 파일
        ↓
Cloudflare R2
        ↓
텍스트 추출 + chunking + embedding
        ↓
LanceDB 또는 Qdrant
        ↓
Streamlit Q&A / Search
```

- 원본 대용량 파일: Cloudflare R2
- 벡터 검색: LanceDB 또는 Qdrant
- 키워드 보조 검색: SQLite FTS
- 답변 생성/임베딩: OpenAI

## 2. Backend modes

`SANDAN_RAG_BACKEND` 값으로 선택합니다.

| Mode | Vector index | Original files | Recommended use |
|---|---|---|---|
| `local` | Chroma + SQLite FTS | local files, optional R2 | local development |
| `lancedb` | LanceDB + SQLite FTS | Cloudflare R2 | low-cost prototype |
| `qdrant` | Qdrant Cloud + optional SQLite FTS | Cloudflare R2 | cloud deployment |
| `supabase` | Supabase pgvector | Cloudflare R2 if configured, otherwise Supabase Storage | pgvector + R2 migration |

## 3. Cloudflare R2 setup

1. Cloudflare Dashboard → `Storage & databases` → `R2 Object Storage` 진입
2. R2 활성화
3. Bucket 생성 예: `sandan-rag-files`
4. `Manage R2 API Tokens` → `Create API token`
5. 권한은 `Object Read & Write`, 범위는 해당 bucket 하나만 선택
6. 아래 값을 `.env` 또는 Streamlit Secrets에 저장

```env
R2_ACCOUNT_ID="your_cloudflare_account_id"
R2_ACCESS_KEY_ID="your_r2_access_key_id"
R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"
R2_BUCKET_NAME="sandan-rag-files"
R2_ENDPOINT_URL="https://your_account_id.r2.cloudflarestorage.com"
R2_SIGNED_URL_SECONDS="3600"
```

R2 bucket은 private으로 두는 것을 권장합니다. 이 시스템은 다운로드 시 presigned URL을 생성합니다.

## 4. LanceDB mode

가장 간단하고 비용이 적은 방식입니다. LanceDB는 별도 회원가입이 필요 없습니다.

`.env` 예시:

```env
OPENAI_API_KEY="sk-xxxx"
OPENAI_CHAT_MODEL="gpt-4.1-mini"
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"

SANDAN_RAG_BACKEND="lancedb"
SANDAN_OBJECT_STORAGE="r2"

R2_ACCOUNT_ID="your_cloudflare_account_id"
R2_ACCESS_KEY_ID="your_r2_access_key_id"
R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"
R2_BUCKET_NAME="sandan-rag-files"
R2_ENDPOINT_URL="https://your_account_id.r2.cloudflarestorage.com"

LANCEDB_PATH="data/lancedb"
LANCEDB_TABLE_NAME="sandan_attachments"
```

실행:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\collect_data.py --max-pages 300
python scripts\build_index.py --force
streamlit run app.py
```

## 5. Qdrant mode

Qdrant Cloud에 회원가입하고 Free Cluster를 만든 뒤 `Cluster URL`과 `Database API Key`를 저장합니다.

`.env` 예시:

```env
OPENAI_API_KEY="sk-xxxx"
OPENAI_CHAT_MODEL="gpt-4.1-mini"
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"

SANDAN_RAG_BACKEND="qdrant"
SANDAN_OBJECT_STORAGE="r2"

QDRANT_URL="https://xxxxxx.eu-central.aws.cloud.qdrant.io"
QDRANT_API_KEY="your_qdrant_database_api_key"
QDRANT_COLLECTION_NAME="sandan_attachments"

R2_ACCOUNT_ID="your_cloudflare_account_id"
R2_ACCESS_KEY_ID="your_r2_access_key_id"
R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"
R2_BUCKET_NAME="sandan-rag-files"
R2_ENDPOINT_URL="https://your_account_id.r2.cloudflarestorage.com"
```

실행:

```powershell
python scripts\collect_data.py --max-pages 300
python scripts\build_index.py --force
streamlit run app.py
```

## 6. Supabase pgvector + Cloudflare R2 mode

Supabase를 벡터 DB(pgvector)로 계속 쓰되, 원본 대용량 파일은 Cloudflare R2에 저장할 수 있습니다. 이 방식에서는 Supabase Storage를 사용하지 않습니다.

`.env` 예시:

```env
OPENAI_API_KEY="sk-xxxx"
OPENAI_CHAT_MODEL="gpt-4.1-mini"
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"

SANDAN_RAG_BACKEND="supabase"
SANDAN_OBJECT_STORAGE="r2"

SUPABASE_URL="https://xxxx.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="xxxx"

R2_ACCOUNT_ID="your_cloudflare_account_id"
R2_ACCESS_KEY_ID="your_r2_access_key_id"
R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"
R2_BUCKET_NAME="sandan-rag-files"
R2_ENDPOINT_URL="https://your_account_id.r2.cloudflarestorage.com"
R2_SIGNED_URL_SECONDS="3600"
```

Supabase SQL Editor에서 `supabase/schema.sql`을 한 번 실행한 뒤 마이그레이션합니다.

```powershell
python scripts\collect_data.py --max-pages 300
python scripts\migrate_local_to_supabase.py --force
```

기존 Supabase Storage 방식으로만 사용하려면 `SANDAN_OBJECT_STORAGE`를 비워두고 `SUPABASE_BUCKET`을 설정하면 됩니다.


## 7. Useful commands

진단:

```powershell
python scripts\diagnose.py
```

강제 재색인:

```powershell
python scripts\build_index.py --force
```

원본 파일 업로드 없이 색인만 재생성:

```powershell
python scripts\build_index.py --force --no-upload-files
```

Streamlit 실행:

```powershell
streamlit run app.py
```

## 8. Streamlit Cloud Secrets example

```toml
OPENAI_API_KEY = "sk-xxxx"
OPENAI_CHAT_MODEL = "gpt-4.1-mini"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

SANDAN_RAG_BACKEND = "qdrant"
SANDAN_OBJECT_STORAGE = "r2"
SANDAN_ENABLE_UPDATE_DIALOG = "false"

QDRANT_URL = "https://xxxxxx.eu-central.aws.cloud.qdrant.io"
QDRANT_API_KEY = "xxxx"
QDRANT_COLLECTION_NAME = "sandan_attachments"

R2_ACCOUNT_ID = "xxxx"
R2_ACCESS_KEY_ID = "xxxx"
R2_SECRET_ACCESS_KEY = "xxxx"
R2_BUCKET_NAME = "sandan-rag-files"
R2_ENDPOINT_URL = "https://xxxx.r2.cloudflarestorage.com"
```

## 9. Important notes

- R2에는 원본 파일만 저장합니다.
- LanceDB/Qdrant에는 chunk text, embedding, metadata, R2 object key가 저장됩니다.
- R2 Secret Access Key는 한 번만 표시되므로 반드시 안전하게 저장하세요.
- R2 bucket을 public으로 열 필요가 없습니다. private bucket + presigned URL 방식을 권장합니다.
- Streamlit Cloud의 로컬 파일 시스템은 장기 저장소가 아니므로, 클라우드 배포는 `qdrant + r2` 조합을 권장합니다.
