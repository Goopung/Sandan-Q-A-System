# KHU Sandan RAG Q&A System

This project is a Streamlit-based RAG Q&A system designed to collect attachment files from Kyung Hee University Research Office / Industry-Academic Cooperation Foundation bulletin boards, extract textual content from the collected files, build a searchable knowledge base, and provide AI-powered question answering with original file download support.

This version supports a **Cloudflare R2 + LanceDB/Qdrant** architecture in order to reduce dependency on Supabase Storage and provide a more scalable and cost-efficient storage structure.

## 1. Recommended Architecture

```text
Original bulletin board attachments
(PDF / HWP / PPT / ZIP)
        ↓
Cloudflare R2
        ↓
Text extraction + chunking + embedding
        ↓
LanceDB or Qdrant
        ↓
Streamlit Q&A / Search Interface
````

* Original large files: Cloudflare R2
* Vector search: LanceDB or Qdrant
* Keyword-based auxiliary search: SQLite FTS
* Answer generation and embeddings: OpenAI

## 2. Backend Modes

The backend mode can be selected using the `SANDAN_RAG_BACKEND` environment variable.

| Mode       | Vector Index                       | Original File Storage                                   | Recommended Use Case                       |
| ---------- | ---------------------------------- | ------------------------------------------------------- | ------------------------------------------ |
| `local`    | Chroma + SQLite FTS                | Local files, optional R2                                | Local development                          |
| `lancedb`  | LanceDB + SQLite FTS               | Cloudflare R2                                           | Low-cost prototype                         |
| `qdrant`   | Qdrant Cloud + optional SQLite FTS | Cloudflare R2                                           | Cloud deployment                           |
| `supabase` | Supabase pgvector                  | Cloudflare R2 if configured, otherwise Supabase Storage | pgvector-based deployment and R2 migration |

## 3. Cloudflare R2 Setup

1. Go to the Cloudflare Dashboard.
2. Navigate to `Storage & databases` → `R2 Object Storage`.
3. Enable R2.
4. Create a bucket, for example: `sandan-rag-files`.
5. Go to `Manage R2 API Tokens` → `Create API Token`.
6. Set the permission to `Object Read & Write`.
7. Restrict the token scope to the target bucket only.
8. Save the following values in `.env` or Streamlit Secrets.

```env
R2_ACCOUNT_ID="your_cloudflare_account_id"
R2_ACCESS_KEY_ID="your_r2_access_key_id"
R2_SECRET_ACCESS_KEY="your_r2_secret_access_key"
R2_BUCKET_NAME="sandan-rag-files"
R2_ENDPOINT_URL="https://your_account_id.r2.cloudflarestorage.com"
R2_SIGNED_URL_SECONDS="3600"
```

It is recommended to keep the R2 bucket private.
This system generates presigned URLs when users need to download original files.

## 4. LanceDB Mode

LanceDB is the simplest and most cost-efficient option for local or lightweight deployment.
It does not require a separate cloud account.

Example `.env` configuration:

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

Run the system:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\collect_data.py --max-pages 300
python scripts\build_index.py --force
streamlit run app.py
```

## 5. Qdrant Mode

Qdrant mode is recommended for cloud deployment.
Create a free Qdrant Cloud cluster and save the `Cluster URL` and `Database API Key`.

Example `.env` configuration:

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

Run the system:

```powershell
python scripts\collect_data.py --max-pages 300
python scripts\build_index.py --force
streamlit run app.py
```

## 6. Supabase pgvector + Cloudflare R2 Mode

This mode allows you to continue using Supabase as the vector database through pgvector, while storing large original files in Cloudflare R2.
In this configuration, Supabase Storage is not used for original file storage.

Example `.env` configuration:

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

Before migration, run `supabase/schema.sql` once in the Supabase SQL Editor.

Then migrate the local index to Supabase:

```powershell
python scripts\collect_data.py --max-pages 300
python scripts\migrate_local_to_supabase.py --force
```

To continue using the legacy Supabase Storage-only mode, leave `SANDAN_OBJECT_STORAGE` empty and configure `SUPABASE_BUCKET`.

## 7. Useful Commands

Run diagnostics:

```powershell
python scripts\diagnose.py
```

Force rebuild the index:

```powershell
python scripts\build_index.py --force
```

Rebuild the index without uploading original files:

```powershell
python scripts\build_index.py --force --no-upload-files
```

Run Streamlit:

```powershell
streamlit run app.py
```

## 8. Streamlit Cloud Secrets Example

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

## 9. Important Notes

* Cloudflare R2 stores only the original files.
* LanceDB or Qdrant stores chunk text, embeddings, metadata, and R2 object keys.
* The R2 Secret Access Key is displayed only once. Store it securely.
* The R2 bucket does not need to be public. A private bucket with presigned URLs is recommended.
* The local file system in Streamlit Cloud is not suitable for long-term persistent storage.
* For cloud deployment, the recommended configuration is `qdrant + r2`.
* For low-cost local development or prototyping, the recommended configuration is `lancedb + r2`.
